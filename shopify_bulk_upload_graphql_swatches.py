#!/usr/bin/env python3
"""GraphQL product uploader that provisions Shopify swatch metaobjects.

Flow:
1) Ensure swatch metaobject + product metafield definitions exist.
2) Create/reuse color metaobjects.
3) Create product shell.
4) Create linked product options.
5) Bulk-create variants.
6) Upload images via REST and link to variants.
7) Patch swatch metaobjects with uploaded image references.
"""

import argparse
import os
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from dotenv import load_dotenv

from shopify_bulk_upload import (
    ParsedImage,
    build_paired_groups,
    build_groups,
    build_product_tags,
    choose_title,
    collect_images,
    get_access_token,
    load_pairings,
    load_product_type_map,
    make_body_html,
    move_uploaded_file,
)
from shopify_bulk_upload import ShopifyClient as RestShopifyClient

DEFAULT_SWATCH_METAOBJECT_TYPE = "custom--color-pattern"
DEFAULT_SWATCH_NAMESPACE = "custom"
DEFAULT_SWATCH_KEY = "color-pattern"

COLOR_HEX_BY_NAME = {
    "black": "#000000",
    "white": "#FFFFFF",
    "red": "#D12A2A",
    "blue soul": "#5C7EA6",
    "butter": "#F5E083",
    "cotton pink": "#F3C9D7",
    "fraiche peche": "#F2B08A",
    "french navy": "#1E2A44",
    "heather grey": "#9FA3A8",
    "khaki": "#8A7B57",
}


class GraphQLShopifyClient:
    def __init__(self, shop_domain: str, access_token: str, api_version: str) -> None:
        self.base_url = f"https://{shop_domain}/admin/api/{api_version}"
        self.session = RestShopifyClient(shop_domain, access_token, api_version).session

    def _request(self, method: str, endpoint: str, json_data: Optional[dict] = None) -> dict:
        url = f"{self.base_url}{endpoint}"
        for _attempt in range(6):
            resp = self.session.request(method=method, url=url, json=json_data, timeout=60)
            if resp.status_code == 429:
                wait_seconds = int(resp.headers.get("Retry-After", "2"))
                import time

                time.sleep(max(wait_seconds, 1))
                continue
            if resp.status_code >= 400:
                raise RuntimeError(f"Shopify API error {resp.status_code} on {method} {endpoint}: {resp.text}")
            if not resp.text:
                return {}
            return resp.json()
        raise RuntimeError(f"Rate-limit retries exceeded for {method} {endpoint}")

    def _graphql(self, query: str, variables: Optional[dict] = None) -> dict:
        payload = {"query": query, "variables": variables or {}}
        data = self._request("POST", "/graphql.json", json_data=payload)
        errors = data.get("errors")
        if errors:
            raise RuntimeError(f"Shopify GraphQL error: {errors}")
        return data.get("data", {})

    @staticmethod
    def _format_user_errors(prefix: str, errors: List[dict]) -> RuntimeError:
        messages = "; ".join(
            f"{','.join(map(str, error.get('field', [])))}: {error.get('message', 'Unknown error')}"
            for error in errors
        )
        return RuntimeError(f"{prefix}: {messages}")

    def create_product_shell(self, product_input: dict) -> dict:
        mutation = """
        mutation CreateProductShell($input: ProductCreateInput!) {
          productCreate(product: $input) {
            product {
              id
              status
              title
            }
            userErrors {
              field
              message
            }
          }
        }
        """
        data = self._graphql(mutation, {"input": product_input})
        payload = data.get("productCreate", {})
        user_errors = payload.get("userErrors", [])
        if user_errors:
            raise self._format_user_errors("Shopify productCreate failed", user_errors)
        product = payload.get("product")
        if not isinstance(product, dict):
            raise RuntimeError("Shopify productCreate did not return a product")
        return product

    def create_product_options(self, product_id: str, options: List[dict]) -> dict:
        mutation = """
        mutation CreateProductOptions(
          $productId: ID!
          $options: [OptionCreateInput!]!
          $variantStrategy: ProductOptionCreateVariantStrategy
        ) {
          productOptionsCreate(
            productId: $productId
            options: $options
            variantStrategy: $variantStrategy
          ) {
            product {
              id
              options {
                id
                name
                linkedMetafield {
                  namespace
                  key
                }
                optionValues {
                  id
                  name
                  linkedMetafieldValue
                }
              }
            }
            userErrors {
              field
              message
            }
          }
        }
        """
        data = self._graphql(
            mutation,
            {
                "productId": product_id,
                "options": options,
                "variantStrategy": "LEAVE_AS_IS",
            },
        )
        payload = data.get("productOptionsCreate", {})
        user_errors = payload.get("userErrors", [])
        if user_errors:
            raise self._format_user_errors("Shopify productOptionsCreate failed", user_errors)
        product = payload.get("product")
        if not isinstance(product, dict):
            raise RuntimeError("Shopify productOptionsCreate did not return a product")
        return product

    def add_linked_option_values(self, product_id: str, option_id: str, linked_metafield_values: List[str]) -> dict:
                mutation = """
                mutation AddLinkedOptionValues(
                    $productId: ID!
                    $option: OptionUpdateInput!
                    $optionValuesToAdd: [OptionValueCreateInput!]
                    $variantStrategy: ProductOptionUpdateVariantStrategy
                ) {
                    productOptionUpdate(
                        productId: $productId
                        option: $option
                        optionValuesToAdd: $optionValuesToAdd
                        variantStrategy: $variantStrategy
                    ) {
                        product {
                            id
                            options {
                                id
                                name
                                optionValues {
                                    id
                                    name
                                    linkedMetafieldValue
                                }
                            }
                        }
                        userErrors {
                            field
                            message
                        }
                    }
                }
                """
                option_values_to_add = [{"linkedMetafieldValue": value} for value in linked_metafield_values]
                data = self._graphql(
                        mutation,
                        {
                                "productId": product_id,
                                "option": {"id": option_id},
                                "optionValuesToAdd": option_values_to_add,
                                "variantStrategy": "LEAVE_AS_IS",
                        },
                )
                payload = data.get("productOptionUpdate", {})
                user_errors = payload.get("userErrors", [])
                if user_errors:
                        raise self._format_user_errors("Shopify productOptionUpdate failed", user_errors)
                product = payload.get("product")
                if not isinstance(product, dict):
                        raise RuntimeError("Shopify productOptionUpdate did not return a product")
                return product

    def bulk_create_variants(self, product_id: str, variants: List[dict]) -> List[dict]:
        mutation = """
        mutation BulkCreateVariants(
          $productId: ID!
          $variants: [ProductVariantsBulkInput!]!
          $strategy: ProductVariantsBulkCreateStrategy
        ) {
          productVariantsBulkCreate(
            productId: $productId
            variants: $variants
            strategy: $strategy
          ) {
            productVariants {
              id
              title
              selectedOptions {
                name
                value
              }
            }
            userErrors {
              field
              message
            }
          }
        }
        """
        data = self._graphql(
            mutation,
            {
                "productId": product_id,
                "variants": variants,
                "strategy": "REMOVE_STANDALONE_VARIANT",
            },
        )
        payload = data.get("productVariantsBulkCreate", {})
        user_errors = payload.get("userErrors", [])
        if user_errors:
            raise self._format_user_errors("Shopify productVariantsBulkCreate failed", user_errors)
        product_variants = payload.get("productVariants", [])
        if not isinstance(product_variants, list):
            raise RuntimeError("Shopify productVariantsBulkCreate did not return variants")
        return product_variants

    def get_metaobject_definition_by_type(self, definition_type: str) -> Optional[dict]:
        query = """
        query MetaobjectDefinitionByType($type: String!) {
          metaobjectDefinitionByType(type: $type) {
            id
            name
            type
            displayNameKey
            hasThumbnailField
                        access {
                            admin
                            storefront
                        }
            fieldDefinitions {
              key
              name
              type {
                name
              }
            }
          }
        }
        """
        data = self._graphql(query, {"type": definition_type})
        return data.get("metaobjectDefinitionByType")

    def create_metaobject_definition(self, definition_input: dict) -> dict:
        mutation = """
        mutation CreateMetaobjectDefinition($definition: MetaobjectDefinitionCreateInput!) {
          metaobjectDefinitionCreate(definition: $definition) {
            metaobjectDefinition {
              id
              name
              type
              displayNameKey
              hasThumbnailField
                            access {
                                admin
                                storefront
                            }
              fieldDefinitions {
                key
                name
              }
            }
            userErrors {
              field
              message
            }
          }
        }
        """
        data = self._graphql(mutation, {"definition": definition_input})
        payload = data.get("metaobjectDefinitionCreate", {})
        user_errors = payload.get("userErrors", [])
        if user_errors:
            raise self._format_user_errors("Shopify metaobjectDefinitionCreate failed", user_errors)
        definition = payload.get("metaobjectDefinition")
        if not isinstance(definition, dict):
            raise RuntimeError("Shopify metaobjectDefinitionCreate did not return a definition")
        return definition

    def get_metaobject_definition_by_id(self, definition_id: str) -> Optional[dict]:
        query = """
        query MetaobjectDefinitionById($id: ID!) {
          node(id: $id) {
            ... on MetaobjectDefinition {
              id
              name
              type
              access {
                admin
                storefront
              }
            }
          }
        }
        """
        data = self._graphql(query, {"id": definition_id})
        node = data.get("node")
        return node if isinstance(node, dict) else None

    def ensure_metaobject_definition_storefront_access(self, definition_id: str) -> bool:
        definition = self.get_metaobject_definition_by_id(definition_id)
        if not definition:
            return False

        access = definition.get("access") or {}
        if access.get("storefront") == "PUBLIC_READ":
            return True

        mutation = """
        mutation UpdateMetaobjectDefinitionAccess($id: ID!, $definition: MetaobjectDefinitionUpdateInput!) {
          metaobjectDefinitionUpdate(id: $id, definition: $definition) {
            metaobjectDefinition {
              id
              access {
                admin
                storefront
              }
            }
            userErrors {
              field
              message
            }
          }
        }
        """
        data = self._graphql(
            mutation,
            {
                "id": definition_id,
                "definition": {
                    "access": {
                        "storefront": "PUBLIC_READ",
                    }
                },
            },
        )
        payload = data.get("metaobjectDefinitionUpdate", {})
        user_errors = payload.get("userErrors", [])
        if user_errors:
            raise self._format_user_errors("Shopify metaobjectDefinitionUpdate failed", user_errors)
        updated = payload.get("metaobjectDefinition")
        if not isinstance(updated, dict):
            return False
        updated_access = updated.get("access") or {}
        return updated_access.get("storefront") == "PUBLIC_READ"

        def add_metaobject_definition_field(self, definition_id: str, field_input: dict) -> bool:
                mutation = """
                mutation AddMetaobjectDefinitionField($id: ID!, $definition: MetaobjectDefinitionUpdateInput!) {
                    metaobjectDefinitionUpdate(id: $id, definition: $definition) {
                        metaobjectDefinition {
                            id
                            fieldDefinitions {
                                key
                            }
                        }
                        userErrors {
                            field
                            message
                        }
                    }
                }
                """
                data = self._graphql(
                        mutation,
                        {
                                "id": definition_id,
                                "definition": {
                                        "fieldDefinitions": [
                                                {"create": field_input},
                                        ]
                                },
                        },
                )
                payload = data.get("metaobjectDefinitionUpdate", {})
                user_errors = payload.get("userErrors", [])
                if user_errors:
                        raise self._format_user_errors("Shopify metaobjectDefinitionUpdate failed", user_errors)
                updated = payload.get("metaobjectDefinition")
                return isinstance(updated, dict)

    def get_metaobject_by_handle(self, definition_type: str, handle: str) -> Optional[dict]:
        query = """
        query MetaobjectByHandle($handle: MetaobjectHandleInput!) {
          metaobjectByHandle(handle: $handle) {
            id
            handle
            type
            displayName
            fields {
              key
              value
              reference {
                __typename
              }
            }
          }
        }
        """
        data = self._graphql(query, {"handle": {"type": definition_type, "handle": handle}})
        return data.get("metaobjectByHandle")

    def create_metaobject(self, metaobject_input: dict) -> dict:
        mutation = """
        mutation CreateMetaobject($metaobject: MetaobjectCreateInput!) {
          metaobjectCreate(metaobject: $metaobject) {
            metaobject {
              id
              handle
              type
              displayName
              fields {
                key
                value
              }
            }
            userErrors {
              field
              message
            }
          }
        }
        """
        data = self._graphql(mutation, {"metaobject": metaobject_input})
        payload = data.get("metaobjectCreate", {})
        user_errors = payload.get("userErrors", [])
        if user_errors:
            raise self._format_user_errors("Shopify metaobjectCreate failed", user_errors)
        metaobject = payload.get("metaobject")
        if not isinstance(metaobject, dict):
            raise RuntimeError("Shopify metaobjectCreate did not return a metaobject")
        return metaobject

    def update_metaobject(self, metaobject_id: str, fields: List[dict]) -> dict:
        mutation = """
        mutation UpdateMetaobject($id: ID!, $metaobject: MetaobjectUpdateInput!) {
          metaobjectUpdate(id: $id, metaobject: $metaobject) {
            metaobject {
              id
              handle
              type
              displayName
              fields {
                key
                value
              }
            }
            userErrors {
              field
              message
            }
          }
        }
        """
        data = self._graphql(mutation, {"id": metaobject_id, "metaobject": {"fields": fields}})
        payload = data.get("metaobjectUpdate", {})
        user_errors = payload.get("userErrors", [])
        if user_errors:
            raise self._format_user_errors("Shopify metaobjectUpdate failed", user_errors)
        metaobject = payload.get("metaobject")
        if not isinstance(metaobject, dict):
            raise RuntimeError("Shopify metaobjectUpdate did not return a metaobject")
        return metaobject

    def get_metafield_definition(self, owner_type: str, namespace: str, key: str) -> Optional[dict]:
        query = """
        query MetafieldDefinition($identifier: MetafieldDefinitionIdentifierInput!) {
          metafieldDefinition(identifier: $identifier) {
            id
            name
            namespace
            key
            type {
              name
            }
            validations {
              name
              value
            }
          }
        }
        """
        data = self._graphql(
            query,
            {
                "identifier": {
                    "ownerType": owner_type,
                    "namespace": namespace,
                    "key": key,
                }
            },
        )
        return data.get("metafieldDefinition")

    def create_metafield_definition(self, definition_input: dict) -> dict:
        mutation = """
        mutation CreateMetafieldDefinition($definition: MetafieldDefinitionInput!) {
          metafieldDefinitionCreate(definition: $definition) {
            createdDefinition {
              id
              name
              namespace
              key
              type {
                name
              }
              validations {
                name
                value
              }
            }
            userErrors {
              field
              message
            }
          }
        }
        """
        data = self._graphql(mutation, {"definition": definition_input})
        payload = data.get("metafieldDefinitionCreate", {})
        user_errors = payload.get("userErrors", [])
        if user_errors:
            raise self._format_user_errors("Shopify metafieldDefinitionCreate failed", user_errors)
        definition = payload.get("createdDefinition")
        if not isinstance(definition, dict):
            raise RuntimeError("Shopify metafieldDefinitionCreate did not return a definition")
        return definition


def _slugify_handle(value: str) -> str:
    handle = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return handle or "swatch"


def _product_numeric_id(product_gid: str) -> int:
    match = re.search(r"(\d+)$", str(product_gid))
    if not match:
        raise ValueError(f"Expected a Shopify product GID, got: {product_gid}")
    return int(match.group(1))


def _media_gid(uploaded: dict) -> Optional[str]:
    if uploaded.get("admin_graphql_api_id"):
        return str(uploaded["admin_graphql_api_id"])
    image_id = uploaded.get("id")
    if image_id is None:
        return None
    return f"gid://shopify/MediaImage/{image_id}"


def _swatch_hex_for_color(color_name: str) -> Optional[str]:
    normalized = re.sub(r"\s+", " ", color_name.strip().lower())
    return COLOR_HEX_BY_NAME.get(normalized)


def ensure_swatch_definition_fields(graphql_client: GraphQLShopifyClient, metaobject_definition: dict) -> None:
    existing_fields = {
        str(field.get("key", ""))
        for field in metaobject_definition.get("fieldDefinitions", [])
        if isinstance(field, dict)
    }
    definition_id = str(metaobject_definition["id"])

    if "label" not in existing_fields:
        graphql_client.add_metaobject_definition_field(
            definition_id,
            {
                "key": "label",
                "name": "Label",
                "type": "single_line_text_field",
                "required": True,
            },
        )

    if "swatch_image" not in existing_fields:
        graphql_client.add_metaobject_definition_field(
            definition_id,
            {
                "key": "swatch_image",
                "name": "Swatch Image",
                "type": "file_reference",
                "required": False,
                "validations": [{"name": "file_type_options", "value": "[\"Image\"]"}],
            },
        )

    if "swatch_color" not in existing_fields:
        graphql_client.add_metaobject_definition_field(
            definition_id,
            {
                "key": "swatch_color",
                "name": "Swatch Color",
                "type": "color",
                "required": False,
            },
        )


def ensure_swatch_schema(
    graphql_client: GraphQLShopifyClient,
    swatch_namespace: str,
    swatch_key: str,
) -> Tuple[dict, dict]:
    metaobject_definition = graphql_client.get_metaobject_definition_by_type(DEFAULT_SWATCH_METAOBJECT_TYPE)
    if not metaobject_definition:
        metaobject_definition = graphql_client.create_metaobject_definition(
            {
                "name": "Moonbeam Color Swatch",
                "type": DEFAULT_SWATCH_METAOBJECT_TYPE,
                "displayNameKey": "label",
                "access": {
                    "admin": "MERCHANT_READ_WRITE",
                    "storefront": "PUBLIC_READ",
                },
                "fieldDefinitions": [
                    {
                        "key": "label",
                        "name": "Label",
                        "type": "single_line_text_field",
                        "required": True,
                    },
                    {
                        "key": "swatch_image",
                        "name": "Swatch Image",
                        "type": "file_reference",
                        "required": False,
                        "validations": [{"name": "file_type_options", "value": "[\"Image\"]"}],
                    },
                ],
            }
        )

    try:
        graphql_client.ensure_metaobject_definition_storefront_access(str(metaobject_definition["id"]))
    except RuntimeError as exc:
        print(f"Warning: could not enforce storefront access for swatch definition {metaobject_definition['id']}: {exc}")

    try:
        ensure_swatch_definition_fields(graphql_client, metaobject_definition)
    except RuntimeError as exc:
        print(f"Warning: could not ensure swatch definition fields for {metaobject_definition['id']}: {exc}")

    metafield_definition = graphql_client.get_metafield_definition("PRODUCT", swatch_namespace, swatch_key)
    if not metafield_definition:
        metafield_definition = graphql_client.create_metafield_definition(
            {
                "name": "Color Swatch",
                "namespace": swatch_namespace,
                "key": swatch_key,
                "description": "Links product color options to reusable swatch metaobjects.",
                "type": "list.metaobject_reference",
                "ownerType": "PRODUCT",
                "validations": [
                    {
                        "name": "metaobject_definition_id",
                        "value": metaobject_definition["id"],
                    }
                ],
            }
        )

    linked_definition_id = None
    for validation in metafield_definition.get("validations", []):
        if validation.get("name") == "metaobject_definition_id" and validation.get("value"):
            linked_definition_id = str(validation["value"])
            break

    if linked_definition_id:
        try:
            graphql_client.ensure_metaobject_definition_storefront_access(linked_definition_id)
        except RuntimeError as exc:
            print(f"Warning: could not enforce storefront access for linked definition {linked_definition_id}: {exc}")

    return metaobject_definition, metafield_definition


def ensure_color_metaobjects(
    graphql_client: GraphQLShopifyClient,
    colors: List[str],
) -> Dict[str, str]:
    color_to_metaobject_id: Dict[str, str] = {}
    for color_name in colors:
        swatch_handle = _slugify_handle(color_name)
        swatch_hex = _swatch_hex_for_color(color_name)
        metaobject = graphql_client.get_metaobject_by_handle(DEFAULT_SWATCH_METAOBJECT_TYPE, swatch_handle)
        if not metaobject:
            fields = [{"key": "label", "value": color_name}]
            if swatch_hex:
                fields.append({"key": "swatch_color", "value": swatch_hex})
            metaobject = graphql_client.create_metaobject(
                {
                    "type": DEFAULT_SWATCH_METAOBJECT_TYPE,
                    "handle": swatch_handle,
                    "fields": fields,
                }
            )
        else:
            existing_values = {
                str(field.get("key", "")): str(field.get("value", ""))
                for field in metaobject.get("fields", [])
                if isinstance(field, dict)
            }
            if swatch_hex and existing_values.get("swatch_color") != swatch_hex:
                graphql_client.update_metaobject(
                    str(metaobject["id"]),
                    [
                        {"key": "swatch_color", "value": swatch_hex},
                    ],
                )
        color_to_metaobject_id[color_name] = str(metaobject["id"])
    return color_to_metaobject_id


def _canonical_images_by_color(images: List[ParsedImage]) -> List[ParsedImage]:
    """Choose one image per color for variant rows, preferring front artwork when present."""
    by_color: Dict[str, List[ParsedImage]] = {}
    for img in images:
        by_color.setdefault(img.color_display, []).append(img)

    canonical: List[ParsedImage] = []
    for color in sorted(by_color.keys(), key=lambda value: value.lower()):
        color_images = by_color[color]
        front = next((item for item in color_images if item.position == "front"), None)
        canonical.append(front if front else color_images[0])
    return canonical


def build_graphql_product_input(
    images: List[ParsedImage],
    title: str,
    description: Optional[str],
    vendor: Optional[str],
    tags: str,
    publish_status: str,
    sizes: Optional[List[str]],
    price_override: Optional[str],
    color_to_metaobject_id: Optional[Dict[str, str]] = None,
    swatch_namespace: Optional[str] = None,
    swatch_key: Optional[str] = None,
) -> dict:
    template_suffix = images[0].style_template_suffix
    product_type = images[0].style_product_type
    effective_description = description if description else images[0].style_description
    description_html = make_body_html(effective_description)
    effective_sizes = sizes if sizes is not None else images[0].style_sizes
    size_price_map = images[0].style_size_prices or {}
    unique_colors = sorted({img.color_display for img in images}, key=lambda value: value.lower())

    if color_to_metaobject_id and swatch_namespace and swatch_key:
        product_options = [
            {
                "name": "Color",
                "linkedMetafield": {
                    "namespace": swatch_namespace,
                    "key": swatch_key,
                },
                "values": [{"linkedMetafieldValue": color_to_metaobject_id[color]} for color in unique_colors],
            }
        ]
    else:
        product_options = [{"name": "Color", "values": [{"name": color} for color in unique_colors]}]

    if effective_sizes:
        product_options.append({"name": "Size", "values": [{"name": size} for size in effective_sizes]})

    variants = []
    variant_images = _canonical_images_by_color(images)
    for img in variant_images:
        if effective_sizes:
            for size in effective_sizes:
                if color_to_metaobject_id and swatch_namespace and swatch_key:
                    color_value = {
                        "optionName": "Color",
                        "name": img.color_display,
                        "linkedMetafieldValue": color_to_metaobject_id[img.color_display],
                    }
                else:
                    color_value = {"optionName": "Color", "name": img.color_display}
                variants.append(
                    {
                        "optionValues": [
                            color_value,
                            {"optionName": "Size", "name": size},
                        ],
                        "inventoryItem": {
                            "sku": f"{img.sku}-{size.replace(' ', '-')}",
                            "tracked": False,
                        },
                        "price": price_override if price_override else size_price_map.get(size, img.style_price),
                    }
                )
        else:
            if color_to_metaobject_id and swatch_namespace and swatch_key:
                color_value = {
                    "optionName": "Color",
                    "name": img.color_display,
                    "linkedMetafieldValue": color_to_metaobject_id[img.color_display],
                }
            else:
                color_value = {"optionName": "Color", "name": img.color_display}
            variants.append(
                {
                    "optionValues": [color_value],
                    "inventoryItem": {
                        "sku": img.sku,
                        "tracked": False,
                    },
                    "price": price_override if price_override else img.style_price,
                }
            )

    product_input = {
        "title": title,
        "descriptionHtml": description_html,
        "productOptions": product_options,
        "variants": variants,
        "tags": tags,
    }
    if vendor:
        product_input["vendor"] = vendor
    if template_suffix:
        product_input["templateSuffix"] = template_suffix
    if product_type:
        product_input["productType"] = product_type
    if publish_status:
        product_input["status"] = publish_status.upper()
    return product_input


def create_products(
    graphql_client: GraphQLShopifyClient,
    rest_client: RestShopifyClient,
    groups: Dict[Tuple[str, str], List[ParsedImage]],
    description: Optional[str],
    price_override: Optional[str],
    vendor: Optional[str],
    uploaded_dir: Path,
    dry_run: bool,
    publish_status: str,
    sizes: Optional[List[str]] = None,
    swatch_namespace: Optional[str] = DEFAULT_SWATCH_NAMESPACE,
    swatch_key: Optional[str] = DEFAULT_SWATCH_KEY,
) -> None:
    total_products = len(groups)
    created = 0

    swatches_enabled = bool(swatch_namespace and swatch_key)
    swatch_definition = None
    swatch_metafield_definition = None
    effective_swatch_namespace = swatch_namespace
    effective_swatch_key = swatch_key

    if not dry_run and swatches_enabled:
        swatch_definition, swatch_metafield_definition = ensure_swatch_schema(
            graphql_client=graphql_client,
            swatch_namespace=swatch_namespace,
            swatch_key=swatch_key,
        )
        effective_swatch_namespace = str(swatch_metafield_definition.get("namespace", swatch_namespace))
        effective_swatch_key = str(swatch_metafield_definition.get("key", swatch_key))

    for (artwork, style_label), images in sorted(groups.items(), key=lambda item: (item[0][0], item[0][1])):
        title = choose_title(images)
        tags = build_product_tags(images)
        unique_colors = sorted({img.color_display for img in images}, key=lambda value: value.lower())

        color_to_metaobject_id: Optional[Dict[str, str]] = None
        if swatches_enabled and swatch_definition and swatch_metafield_definition:
            color_to_metaobject_id = ensure_color_metaobjects(graphql_client, unique_colors)

        product_input = build_graphql_product_input(
            images=images,
            title=title,
            description=description,
            vendor=vendor,
            tags=tags,
            publish_status=publish_status,
            sizes=sizes,
            price_override=price_override,
            color_to_metaobject_id=color_to_metaobject_id,
            swatch_namespace=effective_swatch_namespace,
            swatch_key=effective_swatch_key,
        )

        effective_sizes = sizes if sizes is not None else images[0].style_sizes

        print(f"\nArtwork: {artwork}")
        print(f"  Product type: {style_label}")
        print(f"  Product title: {title}")
        if product_input.get("templateSuffix"):
            print(f"  Template suffix: {product_input['templateSuffix']}")
        if product_input.get("productType"):
            print(f"  Shopify product_type: {product_input['productType']}")
        if product_input.get("descriptionHtml"):
            preview = str(product_input["descriptionHtml"])[:120].replace("\n", " ")
            trailer = "..." if len(str(product_input["descriptionHtml"])) > 120 else ""
            print(f"  Description: {preview}{trailer}")
        print(f"  Tags: {tags}")
        sku_preview = sorted({img.sku for img in images})
        print(f"  SKU range: {sku_preview[0]} ... {sku_preview[-1]}")
        print(f"  Variants: {len(product_input['variants'])}")
        print(f"  Shopify status to set: {publish_status}")
        print(f"  Shopify vendor to set: {vendor or '(none)'}")
        option_summary = "Color swatches" if swatches_enabled else "Color"
        print("  Shopify options to set: " + option_summary + (", Size" if effective_sizes else ""))

        if dry_run:
            for variant in product_input["variants"]:
                option_bits = []
                for item in variant["optionValues"]:
                    value = item.get("name", item.get("linkedMetafieldValue", ""))
                    option_bits.append(f"{item['optionName']}={value}")
                sku_value = variant.get("inventoryItem", {}).get("sku", "")
                print(f"    - {' / '.join(option_bits)} / SKU={sku_value} / Price={variant['price']}")
            continue

        product_shell_input = {
            "title": product_input["title"],
            "descriptionHtml": product_input["descriptionHtml"],
            "tags": product_input["tags"],
        }
        if product_input.get("vendor"):
            product_shell_input["vendor"] = product_input["vendor"]
        if product_input.get("templateSuffix"):
            product_shell_input["templateSuffix"] = product_input["templateSuffix"]
        if product_input.get("productType"):
            product_shell_input["productType"] = product_input["productType"]
        if product_input.get("status"):
            product_shell_input["status"] = product_input["status"]

        if swatches_enabled:
            # Create only non-linked options on productCreate, then add linked Color separately.
            if effective_sizes:
                product_shell_input["productOptions"] = [
                    {"name": "Size", "values": [{"name": size} for size in effective_sizes]}
                ]
        else:
            product_shell_input["productOptions"] = product_input["productOptions"]

        shell_product = graphql_client.create_product_shell(product_shell_input)
        product_gid = str(shell_product["id"])
        variants_payload = list(product_input["variants"])

        if swatches_enabled and color_to_metaobject_id:
            linked_ids = [color_to_metaobject_id[color] for color in unique_colors]
            first_color_option = {
                "name": "Color",
                "linkedMetafield": {
                    "namespace": effective_swatch_namespace,
                    "key": effective_swatch_key,
                    "values": [linked_ids[0]],
                },
            }
            options_product = graphql_client.create_product_options(product_id=product_gid, options=[first_color_option])

            color_option_id = None
            for option in options_product.get("options", []):
                if option.get("name") == "Color":
                    color_option_id = str(option.get("id", ""))
                    break
            if not color_option_id:
                raise RuntimeError("Could not find Color option ID after productOptionsCreate")

            options_state = options_product
            if len(linked_ids) > 1:
                options_state = graphql_client.add_linked_option_values(
                    product_id=product_gid,
                    option_id=color_option_id,
                    linked_metafield_values=linked_ids[1:],
                )

            linked_to_option_value_id: Dict[str, str] = {}
            for option in options_state.get("options", []):
                if option.get("name") != "Color":
                    continue
                for option_value in option.get("optionValues", []):
                    linked_value = str(option_value.get("linkedMetafieldValue", "")).strip()
                    option_value_id = str(option_value.get("id", "")).strip()
                    if linked_value and option_value_id:
                        linked_to_option_value_id[linked_value] = option_value_id

            remapped_variants = []
            for variant in product_input["variants"]:
                new_option_values = []
                for option_value in variant.get("optionValues", []):
                    if option_value.get("optionName") == "Color" and option_value.get("linkedMetafieldValue"):
                        linked_value = str(option_value["linkedMetafieldValue"])
                        option_value_id = linked_to_option_value_id.get(linked_value)
                        if not option_value_id:
                            raise RuntimeError(f"Missing Color option value ID for linked value {linked_value}")
                        new_option_values.append({"optionName": "Color", "id": option_value_id})
                    else:
                        new_option_values.append(option_value)
                remapped_variant = dict(variant)
                remapped_variant["optionValues"] = new_option_values
                remapped_variants.append(remapped_variant)

            variants_payload = remapped_variants

        created_variant_nodes = graphql_client.bulk_create_variants(
            product_id=product_gid,
            variants=variants_payload,
        )

        product_id = _product_numeric_id(product_gid)

        variant_lookup: Dict[object, int] = {}
        for variant in created_variant_nodes:
            variant_id = str(variant.get("id", ""))
            match = re.search(r"(\d+)$", variant_id)
            numeric_variant_id = int(match.group(1)) if match else None
            selected = variant.get("selectedOptions", [])
            if effective_sizes:
                selected_map = {str(item.get("name", "")): str(item.get("value", "")).strip() for item in selected}
                key = (selected_map.get("Color", ""), selected_map.get("Size", ""))
                if all(key) and numeric_variant_id is not None:
                    variant_lookup[key] = numeric_variant_id
            else:
                key = next((str(item.get("value", "")).strip() for item in selected if item.get("name") == "Color"), "")
                if key and numeric_variant_id is not None:
                    variant_lookup[key] = numeric_variant_id

        print(f"  Created Shopify product ID: {product_id}")
        print(f"  Shopify product created with status={shell_product.get('status', '(unknown)')}")
        print("  Shopify variants created:")
        for variant in created_variant_nodes:
            print("    - " f"ID={variant.get('id')}" f" | {variant.get('title', '')}")

        color_to_media_gid: Dict[str, str] = {}

        variant_images_for_linking = _canonical_images_by_color(images)
        variant_image_paths = {img.file_path for img in variant_images_for_linking}

        for img in images:
            uploaded = rest_client.upload_product_image(
                product_id=product_id,
                file_path=img.file_path,
                alt_text=f"{img.artwork_display} - {img.style_label} - {img.color_display}",
            )
            image_id = uploaded["id"]
            media_gid = _media_gid(uploaded)
            if media_gid:
                color_to_media_gid.setdefault(img.color_display, media_gid)
            print(
                "  Shopify image uploaded: "
                f"ID={image_id}"
                f" | File='{img.file_path.name}'"
                f" | Color={img.color_display}"
            )

            if img.file_path not in variant_image_paths:
                moved_to = move_uploaded_file(img.file_path, uploaded_dir)
                print(f"  Moved uploaded file -> '{moved_to}'")
                continue

            if effective_sizes:
                linked_variant_ids: List[int] = []
                for size in effective_sizes:
                    variant_id = variant_lookup.get((img.color_display, size))
                    if variant_id:
                        rest_client.set_variant_image(variant_id=variant_id, image_id=image_id)
                        linked_variant_ids.append(variant_id)
                        print(
                            "    -> Linked in Shopify: "
                            f"image {image_id} -> variant {variant_id} ({img.color_display} / {size})"
                        )
                if linked_variant_ids:
                    print(f"  Image linkage summary: {img.file_path.name} -> variants {linked_variant_ids}")
                else:
                    print(
                        "  Uploaded image but no matching size variants found in Shopify for "
                        f"'{img.file_path.name}'"
                    )
            else:
                variant_id = variant_lookup.get(img.color_display)
                if variant_id:
                    rest_client.set_variant_image(variant_id=variant_id, image_id=image_id)
                    print(
                        "  Linked in Shopify: "
                        f"image {image_id} -> variant {variant_id} ({img.color_display})"
                    )
                else:
                    print(
                        "  Uploaded image but no matching Shopify variant found for "
                        f"'{img.file_path.name}'"
                    )

            moved_to = move_uploaded_file(img.file_path, uploaded_dir)
            print(f"  Moved uploaded file -> '{moved_to}'")

        if swatches_enabled and color_to_metaobject_id:
            for color_name, metaobject_id in color_to_metaobject_id.items():
                media_gid = color_to_media_gid.get(color_name)
                if not media_gid:
                    continue
                try:
                    fields = [
                        {"key": "label", "value": color_name},
                        {"key": "swatch_image", "value": media_gid},
                    ]
                    swatch_hex = _swatch_hex_for_color(color_name)
                    if swatch_hex:
                        fields.append({"key": "swatch_color", "value": swatch_hex})
                    graphql_client.update_metaobject(
                        metaobject_id,
                        fields,
                    )
                except RuntimeError as exc:
                    print(f"  Swatch image update failed for color '{color_name}': {exc}")

        created += 1

    print("\nDone")
    if dry_run:
        print(f"Dry-run complete. Products previewed: {total_products}")
    else:
        print(f"Products created: {created}/{total_products}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create Shopify products with linked swatches via GraphQL mutations."
    )
    parser.add_argument("folder_positional", nargs="?", help="Folder containing generated images (positional fallback)")
    parser.add_argument("--folder", default=None, help="Folder containing generated images")
    parser.add_argument("--description", default=None, help="Optional description text added to all created products")
    parser.add_argument("--price", default=None, help="Optional override price for all variants")
    parser.add_argument("--vendor", default=None, help="Optional Shopify product vendor")
    parser.add_argument("--dry-run", action="store_true", help="Preview parsing/grouping without creating products in Shopify")
    parser.add_argument(
        "--product-type-map",
        default="product_type_map.json",
        help="Path to JSON lookup for filename style code -> Shopify product type label",
    )
    parser.add_argument(
        "--uploaded-dir",
        default="uploaded",
        help="Folder to move uploaded images into (relative paths are resolved inside --folder)",
    )
    parser.add_argument(
        "--publish-status",
        default="draft",
        choices=["draft", "active"],
        help="Set Shopify products to draft (default) or active",
    )
    parser.add_argument("--sizes", default=None, help="Comma-separated sizes to create as variants")
    parser.add_argument(
        "--swatch-namespace",
        default=DEFAULT_SWATCH_NAMESPACE,
        help="Metafield namespace to link Color to for swatches (empty to disable)",
    )
    parser.add_argument(
        "--swatch-key",
        default=DEFAULT_SWATCH_KEY,
        help="Metafield key to link Color to for swatches (empty to disable)",
    )
    return parser.parse_args()


def main() -> int:
    load_dotenv()
    args = parse_args()

    folder_arg = args.folder or args.folder_positional
    if not folder_arg:
        print("Missing folder. Use --folder PATH or provide PATH as first argument.")
        return 1

    folder = Path(folder_arg)
    product_type_map_path = Path(args.product_type_map)
    uploaded_dir_arg = Path(args.uploaded_dir)
    uploaded_dir = uploaded_dir_arg if uploaded_dir_arg.is_absolute() else folder / uploaded_dir_arg

    try:
        product_type_map = load_product_type_map(product_type_map_path)
        parsed_images = collect_images(folder, product_type_map, skip_dir=uploaded_dir)
        pairings = load_pairings(folder)
        groups = build_paired_groups(parsed_images, pairings) if pairings else build_groups(parsed_images)
    except Exception as exc:
        print(f"Error while parsing folder: {exc}")
        return 1

    print(f"Found {len(parsed_images)} image files")
    print(f"Grouped into {len(groups)} artwork/product-type products")

    graphql_client = None
    rest_client = None

    if not args.dry_run:
        shop_domain = os.getenv("SHOPIFY_SHOP_DOMAIN", "").strip()
        api_version = os.getenv("SHOPIFY_API_VERSION", "2026-07").strip()

        if not shop_domain:
            print("Missing SHOPIFY_SHOP_DOMAIN in environment/.env")
            return 1

        try:
            access_token = get_access_token(shop_domain)
        except Exception as exc:
            print(f"Authentication error: {exc}")
            return 1

        graphql_client = GraphQLShopifyClient(shop_domain=shop_domain, access_token=access_token, api_version=api_version)
        rest_client = RestShopifyClient(shop_domain=shop_domain, access_token=access_token, api_version=api_version)

    sizes = [item.strip() for item in args.sizes.split(",") if item.strip()] if args.sizes else None
    swatch_namespace = args.swatch_namespace.strip() if args.swatch_namespace else ""
    swatch_key = args.swatch_key.strip() if args.swatch_key else ""
    if not swatch_namespace or not swatch_key:
        swatch_namespace = None
        swatch_key = None

    try:
        create_products(
            graphql_client=graphql_client,
            rest_client=rest_client,
            groups=groups,
            description=args.description,
            price_override=args.price,
            vendor=args.vendor,
            uploaded_dir=uploaded_dir,
            dry_run=args.dry_run,
            publish_status=args.publish_status,
            sizes=sizes,
            swatch_namespace=swatch_namespace,
            swatch_key=swatch_key,
        )
    except Exception as exc:
        print(f"Error during Shopify upload: {exc}")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
