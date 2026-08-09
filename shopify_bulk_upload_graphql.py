#\!/usr/bin/env python3
"""GraphQL product uploader with linked option-value metafields for Color and Size."""

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from dotenv import load_dotenv

from shopify_bulk_upload import (
    ParsedImage,
    build_groups,
    build_product_tags,
    choose_title,
    collect_images,
    get_access_token,
    load_product_type_map,
    make_body_html,
    move_uploaded_file,
)
from shopify_bulk_upload import ShopifyClient as RestShopifyClient

DEFAULT_SWATCH_NAMESPACE = "custom"
DEFAULT_SWATCH_KEY = "color-pattern"


class GraphQLShopifyClient:
    def __init__(self, shop_domain: str, access_token: str, api_version: str) -> None:
        self.base_url = f"https://{shop_domain}/admin/api/{api_version}"
        self.session = RestShopifyClient(shop_domain, access_token, api_version).session
        GraphQLShopifyClient._load_color_hex_map()
        self._taxonomy_cache: Dict[str, Optional[str]] = {}

    def resolve_taxonomy_category(self, category: str) -> Optional[str]:
        """Resolve a category name or GID to a Shopify taxonomy GID.
        If category already looks like a GID, return it directly.
        Otherwise search the taxonomy and return the best match GID, or None."""
        if not category:
            return None
        if category.startswith("gid://"):
            return category
        cache_key = category.lower().strip()
        if cache_key in self._taxonomy_cache:
            return self._taxonomy_cache[cache_key]
        query = """
        query SearchTaxonomy($search: String!) {
          taxonomy {
            categories(first: 10, search: $search) {
              nodes {
                id
                name
                fullName
              }
            }
          }
        }
        """
        try:
            data = self._graphql(query, {"search": category})
            nodes = (data.get("taxonomy") or {}).get("categories", {}).get("nodes") or []
            gid = nodes[0]["id"] if nodes else None
            if gid:
                print(f"  Resolved category '{category}' -> {nodes[0].get('fullName', gid)}")
            else:
                print(f"  Warning: no taxonomy category found for '{category}'")
            self._taxonomy_cache[cache_key] = gid
            return gid
        except Exception as exc:
            print(f"  Warning: taxonomy lookup failed for '{category}': {exc}")
            self._taxonomy_cache[cache_key] = None
            return None

    def _request(self, method: str, endpoint: str, json_data: Optional[dict] = None) -> dict:
        url = f"{self.base_url}{endpoint}"
        for attempt in range(6):
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
    def _slugify_handle(value: str) -> str:
        handle = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
        return handle or "value"

    def get_metaobject_definition_by_type(self, definition_type: str) -> Optional[dict]:
        query = """
        query MetaobjectDefinitionByType($type: String!) {
          metaobjectDefinitionByType(type: $type) {
            id
            name
            type
            displayNameKey
            fieldDefinitions {
              key
              name
              required
              type {
                name
              }
            }
          }
        }
        """
        data = self._graphql(query, {"type": definition_type})
        return data.get("metaobjectDefinitionByType")

    def get_metaobject_definition_by_id(self, definition_id: str) -> Optional[dict]:
        query = """
        query MetaobjectDefinitionById($id: ID!) {
          node(id: $id) {
            ... on MetaobjectDefinition {
              id
              name
              type
              fieldDefinitions {
                key
                name
                required
                type {
                  name
                }
              }
            }
          }
        }
        """
        data = self._graphql(query, {"id": definition_id})
        node = data.get("node")
        return node if isinstance(node, dict) and node.get("type") else None

    # Simple color-name → hex map loaded from color_hex_map.json (next to this script).
    # Falls back to built-in defaults if the file is missing.
    _COLOR_HEX_DEFAULTS: Dict[str, str] = {}

    @classmethod
    def _load_color_hex_map(cls) -> None:
        map_path = Path(__file__).parent / "color_hex_map.json"
        if map_path.exists():
            with open(map_path, encoding="utf-8") as f:
                cls._COLOR_HEX_DEFAULTS = {k.lower().strip(): v for k, v in json.load(f).items()}
        else:
            cls._COLOR_HEX_DEFAULTS = {
                "black": "#000000", "white": "#FFFFFF", "red": "#D12A2A",
                "blue": "#5C7EA6", "blue soul": "#5C7EA6", "butter": "#F5E083",
                "cotton pink": "#F3C9D7", "fraiche peche": "#F2B08A",
                "french navy": "#1E2A44", "heather grey": "#9FA3A8",
                "khaki": "#8A7B57", "ice blue": "#A8C4D4", "green": "#4A8B5E",
                "yellow": "#F0D060", "orange": "#E8843A", "purple": "#7B5EA7",
                "pink": "#F4A7B9", "grey": "#9FA3A8", "gray": "#9FA3A8",
                "navy": "#1E2A44", "brown": "#7D5A3C",
            }

    def _build_metaobject_fields(self, field_definitions: list, value_name: str) -> List[dict]:
        """Build field values for a metaobject, handling color and text field types."""
        normalized = value_name.lower().strip()
        hex_color = self._COLOR_HEX_DEFAULTS.get(normalized, "#808080")
        fields = []
        for fd in field_definitions:
            field_key = fd.get("key", "")
            field_type = (fd.get("type") or {}).get("name", "") or ""
            if field_type == "color":
                fields.append({"key": field_key, "value": hex_color})
            elif field_type in ("single_line_text_field", "multi_line_text_field") or field_key == "label":
                fields.append({"key": field_key, "value": value_name})
            # Skip file_reference and other complex types -- they are optional on built-in types.
        return fields or [{"key": "label", "value": value_name}]

    def create_metaobject_definition(self, definition_input: dict) -> dict:
        mutation = """
        mutation CreateMetaobjectDefinition($definition: MetaobjectDefinitionCreateInput!) {
          metaobjectDefinitionCreate(definition: $definition) {
            metaobjectDefinition {
              id
              name
              type
              displayNameKey
            }
            userErrors {
              field
              message
            }
          }
        }
        """
        data = self._graphql(mutation, {"definition": definition_input})
        payload = data.get("metaobjectDefinitionCreate") or {}
        user_errors = payload.get("userErrors") or []
        if user_errors:
            messages = "; ".join(
                f"{','.join(map(str, error.get('field') or []))}: {error.get('message', 'Unknown error')}"
                for error in user_errors
            )
            raise RuntimeError(f"Shopify metaobjectDefinitionCreate failed: {messages}")

        definition = payload.get("metaobjectDefinition")
        if not isinstance(definition, dict):
            raise RuntimeError("Shopify metaobjectDefinitionCreate did not return a definition")
        return definition

    def get_metafield_definition(self, owner_type: str, namespace: str, key: str) -> Optional[dict]:
        query = """
        query MetafieldDefinition($identifier: MetafieldDefinitionIdentifierInput!) {
          metafieldDefinition(identifier: $identifier) {
            id
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
        data = self._graphql(query, {"identifier": {"ownerType": owner_type, "namespace": namespace, "key": key}})
        definition = data.get("metafieldDefinition")
        return definition if isinstance(definition, dict) else None

    def create_metafield_definition(self, definition_input: dict) -> dict:
        mutation = """
        mutation CreateMetafieldDefinition($definition: MetafieldDefinitionInput!) {
          metafieldDefinitionCreate(definition: $definition) {
            createdDefinition {
              id
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
        payload = data.get("metafieldDefinitionCreate") or {}
        user_errors = payload.get("userErrors") or []
        if user_errors:
            messages = "; ".join(
                f"{','.join(map(str, error.get('field') or []))}: {error.get('message', 'Unknown error')}"
                for error in user_errors
            )
            raise RuntimeError(f"Shopify metafieldDefinitionCreate failed: {messages}")

        definition = payload.get("createdDefinition")
        if not isinstance(definition, dict):
            raise RuntimeError("Shopify metafieldDefinitionCreate did not return a definition")
        return definition

    def get_metaobject_by_handle(self, definition_type: str, handle: str) -> Optional[dict]:
        query = """
        query MetaobjectByHandle($handle: MetaobjectHandleInput!) {
          metaobjectByHandle(handle: $handle) {
            id
            handle
            type
            displayName
          }
        }
        """
        data = self._graphql(query, {"handle": {"type": definition_type, "handle": handle}})
        metaobject = data.get("metaobjectByHandle")
        return metaobject if isinstance(metaobject, dict) else None

    def list_metaobjects_by_type(self, definition_type: str, max_entries: int = 250) -> List[dict]:
        query = """
        query ListMetaobjects($type: String!, $first: Int!) {
          metaobjects(type: $type, first: $first) {
            nodes {
              id
              handle
              displayName
              fields {
                key
                value
              }
            }
          }
        }
        """
        data = self._graphql(query, {"type": definition_type, "first": max_entries})
        nodes = (data.get("metaobjects") or {}).get("nodes") or []
        return nodes if isinstance(nodes, list) else []

    def create_metaobject(self, metaobject_input: dict) -> dict:
        mutation = """
        mutation CreateMetaobject($metaobject: MetaobjectCreateInput!) {
          metaobjectCreate(metaobject: $metaobject) {
            metaobject {
              id
              handle
              type
              displayName
            }
            userErrors {
              field
              message
            }
          }
        }
        """
        data = self._graphql(mutation, {"metaobject": metaobject_input})
        payload = data.get("metaobjectCreate") or {}
        user_errors = payload.get("userErrors") or []
        if user_errors:
            messages = "; ".join(
                f"{','.join(map(str, error.get('field') or []))}: {error.get('message', 'Unknown error')}"
                for error in user_errors
            )
            raise RuntimeError(f"Shopify metaobjectCreate failed: {messages}")

        metaobject = payload.get("metaobject")
        if not isinstance(metaobject, dict):
            raise RuntimeError("Shopify metaobjectCreate did not return a metaobject")
        return metaobject

    def ensure_option_value_link_targets(self, namespace: str, key: str, option_name: str, value_names: List[str]) -> Dict[str, str]:
        if not namespace or not key or not value_names:
            return {}

        # For the built-in Shopify namespace, metafield definitions are platform-managed and
        # won't appear in metafieldDefinition queries. The metaobject type follows shopify--{key}.
        if namespace == "shopify":
            metaobject_type = f"shopify--{self._slugify_handle(key)}"
            obj_field_definitions: list = []
        else:
            # For custom/app namespaces, discover the linked metaobject type from the definition.
            metafield_definition = self.get_metafield_definition("PRODUCT", namespace, key)
            metaobject_type = None
            obj_field_definitions = []

            if metafield_definition:
                for validation in (metafield_definition.get("validations") or []):
                    if validation.get("name") == "metaobject_definition_id" and validation.get("value"):
                        linked_def = self.get_metaobject_definition_by_id(str(validation["value"]))
                        if linked_def:
                            metaobject_type = linked_def.get("type")
                            obj_field_definitions = linked_def.get("fieldDefinitions") or []
                        break

            if not metaobject_type:
                # No existing metafield with a known metaobject type -- create our own.
                # Use just the key (not namespace+key) so the type is custom--color-pattern,
                # matching the swatches uploader convention.
                derived_type = f"custom--{self._slugify_handle(key)}"
                # For Color options include a swatch_color field so themes can display the colour.
                is_color_option = option_name.lower() == "color"
                api_field_defs = [
                    {"key": "label", "name": "Label", "type": "single_line_text_field", "required": True},
                ]
                local_field_defs: list = [
                    {"key": "label", "name": "Label", "type": {"name": "single_line_text_field"}, "required": True},
                ]
                if is_color_option:
                    api_field_defs.append({"key": "color", "name": "Color", "type": "color", "required": False})
                    local_field_defs.append({"key": "color", "name": "Color", "type": {"name": "color"}, "required": False})

                obj_definition = self.get_metaobject_definition_by_type(derived_type)
                if not obj_definition:
                    obj_definition = self.create_metaobject_definition(
                        {
                            "name": f"{namespace}.{key} option values",
                            "type": derived_type,
                            "displayNameKey": "label",
                            "access": {"storefront": "PUBLIC_READ"},
                            "fieldDefinitions": api_field_defs,
                        }
                    )
                metaobject_type = derived_type
                obj_field_definitions = local_field_defs
                if not metafield_definition:
                    self.create_metafield_definition(
                        {
                            "name": f"{namespace}.{key}",
                            "namespace": namespace,
                            "key": key,
                            "description": f"Links {option_name} option values to metaobjects",
                            "type": "list.metaobject_reference",
                            "ownerType": "PRODUCT",
                            "validations": [{"name": "metaobject_definition_id", "value": obj_definition["id"]}],
                        }
                    )

        # Build a display-name -> GID map for all existing metaobjects of this type.
        # When there are multiple entries with the same display name (e.g., an admin-created
        # entry alongside an incomplete ghost from a previous failed API run), prefer the
        # entry with the most non-null field values (the complete one).
        existing = self.list_metaobjects_by_type(metaobject_type)
        display_name_to_gid: Dict[str, str] = {}
        display_name_to_score: Dict[str, int] = {}
        for e in existing:
            if not e.get("id"):
                continue
            name_key = (e.get("displayName") or "").lower().strip()
            if not name_key:
                continue
            gid = str(e["id"])
            # Count non-null field values -- admin-created entries have more filled fields
            # than ghost entries created by failed API calls (which have only 'label' set).
            score = sum(1 for f in (e.get("fields") or []) if f.get("value") is not None)
            if name_key not in display_name_to_gid or score > display_name_to_score.get(name_key, -1):
                display_name_to_gid[name_key] = gid
                display_name_to_score[name_key] = score

        shopify_managed = metaobject_type.startswith("shopify--")
        result: Dict[str, str] = {}
        for value_name in value_names:
            key_lower = value_name.lower().strip()
            gid = display_name_to_gid.get(key_lower)

            if not gid and not shopify_managed:
                handle = self._slugify_handle(value_name)
                fields = self._build_metaobject_fields(obj_field_definitions, value_name)
                new_obj = self.create_metaobject(
                    {"type": metaobject_type, "handle": handle, "fields": fields}
                )
                gid = str(new_obj["id"])

            if gid:
                result[key_lower] = gid
            else:
                print(f"    Note: no '{metaobject_type}' entry with display name '{value_name}' -- skipping link for this value.")
        return result

    def create_product(self, product_input: dict) -> dict:
        """Create a product including options and variants in a single productSet call."""
        mutation = """
        mutation CreateProduct($synchronous: Boolean!, $input: ProductSetInput!) {
          productSet(synchronous: $synchronous, input: $input) {
            product {
              id
              status
              title
              options {
                id
                name
                optionValues {
                  id
                  name
                  linkedMetafieldValue
                }
              }
              variants(first: 100) {
                nodes {
                  id
                  title
                  selectedOptions {
                    name
                    value
                  }
                }
              }
            }
            userErrors {
              field
              message
              code
            }
          }
        }
        """
        data = self._graphql(mutation, {"synchronous": True, "input": product_input})
        payload = data.get("productSet") or {}
        user_errors = payload.get("userErrors") or []
        if user_errors:
            messages = "; ".join(
                f"{','.join(map(str, error.get('field') or []))}: {error.get('message', 'Unknown error')}"
                for error in user_errors
            )
            raise RuntimeError(f"Shopify productSet failed: {messages}")

        product = payload.get("product")
        if not isinstance(product, dict):
            raise RuntimeError("Shopify productSet did not return a product")
        return product

    def create_product_shell(self, product_input: dict) -> dict:
        """Create a product with metadata only -- no options or variants."""
        shell_input = {k: v for k, v in product_input.items() if k not in ("productOptions", "variants")}
        mutation = """
        mutation CreateProductShell($synchronous: Boolean!, $input: ProductSetInput!) {
          productSet(synchronous: $synchronous, input: $input) {
            product { id status title }
            userErrors { field message code }
          }
        }
        """
        data = self._graphql(mutation, {"synchronous": True, "input": shell_input})
        payload = data.get("productSet") or {}
        user_errors = payload.get("userErrors") or []
        if user_errors:
            messages = "; ".join(
                f"{','.join(map(str, e.get('field') or []))}: {e.get('message', 'Unknown error')}"
                for e in user_errors
            )
            raise RuntimeError(f"Shopify productSet (shell) failed: {messages}")
        product = payload.get("product")
        if not isinstance(product, dict):
            raise RuntimeError("Shopify productSet did not return a product")
        return product

    def create_product_options_with_link(self, product_id: str, options: List[dict]) -> dict:
        """Create product options (optionally linked to metafields) via productOptionsCreate."""
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
                optionValues { id name linkedMetafieldValue }
              }
            }
            userErrors { field message }
          }
        }
        """
        data = self._graphql(
            mutation,
            {"productId": product_id, "options": options, "variantStrategy": "LEAVE_AS_IS"},
        )
        payload = data.get("productOptionsCreate") or {}
        user_errors = payload.get("userErrors") or []
        if user_errors:
            messages = "; ".join(
                f"{','.join(map(str, e.get('field') or []))}: {e.get('message', 'Unknown error')}"
                for e in user_errors
            )
            raise RuntimeError(f"Shopify productOptionsCreate failed: {messages}")
        product = payload.get("product")
        if not isinstance(product, dict):
            raise RuntimeError("Shopify productOptionsCreate did not return a product")
        return product

    def bulk_create_variants(self, product_id: str, variants: List[dict]) -> List[dict]:
        """Create variants via productVariantsBulkCreate."""
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
              selectedOptions { name value }
            }
            userErrors { field message }
          }
        }
        """
        data = self._graphql(
            mutation,
            {"productId": product_id, "variants": variants, "strategy": "REMOVE_STANDALONE_VARIANT"},
        )
        payload = data.get("productVariantsBulkCreate") or {}
        user_errors = payload.get("userErrors") or []
        if user_errors:
            messages = "; ".join(
                f"{','.join(map(str, e.get('field') or []))}: {e.get('message', 'Unknown error')}"
                for e in user_errors
            )
            raise RuntimeError(f"Shopify productVariantsBulkCreate failed: {messages}")
        variants_result = payload.get("productVariants") or []
        return variants_result if isinstance(variants_result, list) else []

    def update_product_template(self, product_id: str, template_suffix: str) -> None:
        """Re-assert the template suffix on a product after creation."""
        mutation = """
        mutation UpdateProductTemplate($input: ProductInput!) {
          productUpdate(input: $input) {
            product { id templateSuffix }
            userErrors { field message }
          }
        }
        """
        data = self._graphql(mutation, {"input": {"id": product_id, "templateSuffix": template_suffix}})
        payload = data.get("productUpdate") or {}
        user_errors = payload.get("userErrors") or []
        if user_errors:
            messages = "; ".join(
                f"{','.join(map(str, e.get('field') or []))}: {e.get('message', 'Unknown error')}"
                for e in user_errors
            )
            raise RuntimeError(f"Shopify productUpdate (template) failed: {messages}")

    def publish_product_to_online_store(self, product_id: str) -> None:
        """Publish a product to the Online Store sales channel."""
        # First get the Online Store publication ID
        query = """
        query GetPublications {
          publications(first: 10) {
            nodes { id name }
          }
        }
        """
        data = self._graphql(query, {})
        publications = (data.get("publications") or {}).get("nodes") or []
        online_store_id = next(
            (p["id"] for p in publications if "online store" in (p.get("name") or "").lower()),
            None,
        )
        if not online_store_id:
            return

        mutation = """
        mutation PublishProduct($id: ID!, $input: [PublicationInput!]!) {
          publishablePublish(id: $id, input: $input) {
            publishable { ... on Product { id } }
            userErrors { field message }
          }
        }
        """
        data = self._graphql(mutation, {"id": product_id, "input": [{"publicationId": online_store_id}]})
        payload = data.get("publishablePublish") or {}
        user_errors = payload.get("userErrors") or []
        if user_errors:
            messages = "; ".join(
                f"{','.join(map(str, e.get('field') or []))}: {e.get('message', 'Unknown error')}"
                for e in user_errors
            )
            raise RuntimeError(f"Shopify publishablePublish failed: {messages}")

    def update_product_option_link(
        self,
        product_id: str,
        option_id: str,
        option_name: str,
        namespace: str,
        key: str,
        name_to_gid: Dict[str, str],
        option_values: List[dict],
    ) -> dict:
        """Single-call link: sets linkedMetafield on the option and all linkedMetafieldValues together.
        Shopify requires both in the same mutation; every existing value must have a GID."""
        values_to_update = []
        missing = []
        for ov in option_values:
            name = (ov.get("name") or "")
            gid = name_to_gid.get(name.lower().strip())
            if gid:
                values_to_update.append({"id": ov["id"], "linkedMetafieldValue": gid})
            else:
                missing.append(name)

        if missing:
            raise RuntimeError(
                f"Cannot link {option_name} option to {namespace}.{key}: "
                f"no metaobject found for value(s): {', '.join(missing)}"
            )
        if not values_to_update:
            return {}

        mutation = """
        mutation LinkOptionAndValues($productId: ID!, $option: OptionUpdateInput!, $optionValuesToUpdate: [OptionValueUpdateInput!], $variantStrategy: ProductOptionUpdateVariantStrategy) {
          productOptionUpdate(productId: $productId, option: $option, optionValuesToUpdate: $optionValuesToUpdate, variantStrategy: $variantStrategy) {
            product {
              id
              options {
                id
                name
                optionValues { id name linkedMetafieldValue }
              }
            }
            userErrors { field message code }
          }
        }
        """
        data = self._graphql(
            mutation,
            {
                "productId": product_id,
                "option": {"id": option_id, "linkedMetafield": {"namespace": namespace, "key": key}},
                "optionValuesToUpdate": values_to_update,
                "variantStrategy": "LEAVE_AS_IS",
            },
        )
        payload = data.get("productOptionUpdate") or {}
        user_errors = payload.get("userErrors") or []
        if user_errors:
            messages = "; ".join(
                f"{','.join(map(str, e.get('field') or []))}: {e.get('message', 'Unknown error')}"
                for e in user_errors
            )
            raise RuntimeError(f"Shopify productOptionUpdate failed: {messages}")
        product = payload.get("product")
        if not isinstance(product, dict):
            raise RuntimeError("Shopify productOptionUpdate did not return a product")
        return product


def gid_to_numeric_id(gid: object) -> int:
    text = str(gid)
    match = re.search(r"(\d+)$", text)
    if not match:
        raise ValueError(f"Expected a Shopify GID ending in a numeric ID, got: {gid}")
    return int(match.group(1))


def build_graphql_product_input(
    images: List[ParsedImage],
    title: str,
    description: Optional[str],
    vendor: Optional[str],
    tags: str,
    publish_status: str,
    sizes: Optional[List[str]],
    price_override: Optional[str],
    swatch_namespace: Optional[str],
    swatch_key: Optional[str],
    size_namespace: Optional[str],
    size_key: Optional[str],
    use_swatches: bool,
    category_gid: Optional[str] = None,
) -> dict:
    template_suffix = images[0].style_template_suffix
    product_type = images[0].style_product_type
    effective_description = description if description else images[0].style_description
    description_html = make_body_html(effective_description)
    effective_sizes = sizes if sizes is not None else images[0].style_sizes
    size_price_map = images[0].style_size_prices or {}
    unique_colors = sorted({img.color_display for img in images}, key=lambda value: value.lower())

    def build_option_value(value: str) -> dict:
        return {"name": value}

    use_color_links = bool(use_swatches and swatch_namespace and swatch_key)
    use_size_links = bool(size_namespace and size_key)

    product_options: List[dict] = []
    product_options.append(
        {
            "name": "Color",
            "position": 1,
            "values": [build_option_value(color) for color in unique_colors],
        }
    )

    if effective_sizes:
        product_options.append({"name": "Size", "position": 2, "values": [{"name": size} for size in effective_sizes]})

    variants = []
    for img in sorted(images, key=lambda item: item.color_display):
        if effective_sizes:
            for size in effective_sizes:
                variants.append(
                    {
                        "optionValues": [
                            {"optionName": "Color", **build_option_value(img.color_display)},
                            {"optionName": "Size", **build_option_value(size)},
                        ],
                        "sku": f"{img.sku}-{size.replace(' ', '-')}",
                        "price": price_override if price_override else size_price_map.get(size, img.style_price),
                    }
                )
        else:
            variants.append(
                {
                    "optionValues": [{"optionName": "Color", **build_option_value(img.color_display)}],
                    "sku": img.sku,
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
    if category_gid:
        product_input["productCategory"] = {"productTaxonomyNodeId": category_gid}
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
    size_namespace: Optional[str] = None,
    size_key: Optional[str] = None,
) -> None:
    total_products = len(groups)
    created = 0

    for (artwork, style_label), images in sorted(groups.items(), key=lambda item: (item[0][0], item[0][1])):
        title = choose_title(images)
        tags = build_product_tags(images)
        use_swatches_enabled = bool(swatch_namespace and swatch_key)
        # Resolve Shopify taxonomy category GID (search term or direct GID from product map)
        category_gid: Optional[str] = None
        raw_category = images[0].style_category
        if raw_category:
            category_gid = graphql_client.resolve_taxonomy_category(raw_category)
        product_input = build_graphql_product_input(
            images=images,
            title=title,
            description=description,
            vendor=vendor,
            tags=tags,
            publish_status=publish_status,
            sizes=sizes,
            price_override=price_override,
            swatch_namespace=swatch_namespace,
            swatch_key=swatch_key,
            size_namespace=size_namespace,
            size_key=size_key,
            use_swatches=use_swatches_enabled,
            category_gid=category_gid,
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
            print(f"  Description: {preview}{'...' if len(str(product_input['descriptionHtml'])) > 120 else ''}")
        print(f"  Tags: {tags}")
        sku_preview = sorted({img.sku for img in images})
        print(f"  SKU range: {sku_preview[0]} ... {sku_preview[-1]}")
        print(f"  Variants: {len(product_input['variants'])}")
        print(f"  Shopify status to set: {publish_status}")
        print(f"  Shopify vendor to set: {vendor or '(none)'}")
        option_summary = "Color swatches" if swatch_namespace and swatch_key else "Color"
        print("  Shopify options to set: " + option_summary + (", Size" if effective_sizes else ""))

        if dry_run:
            for variant in product_input["variants"]:
                option_bits = []
                for item in variant["optionValues"]:
                    value = item.get("name", item.get("linkedMetafieldValue", ""))
                    option_bits.append(f"{item['optionName']}={value}")
                print(f"    - {' / '.join(option_bits)} / SKU={variant['sku']} / Price={variant['price']}")
            continue

        # --- STEP 1: Create product with plain options via productSet (always reliable) ---
        try:
            product = graphql_client.create_product(product_input)
        except RuntimeError as error:
            error_text = str(error)
            if swatch_namespace and swatch_key and "color-pattern" in error_text:
                print("  Retrying with plain Color options.")
                product_input = build_graphql_product_input(
                    images=images, title=title, description=description, vendor=vendor,
                    tags=tags, publish_status=publish_status, sizes=sizes,
                    price_override=price_override,
                    swatch_namespace=None, swatch_key=None,
                    size_namespace=size_namespace, size_key=size_key, use_swatches=False,
                    category_gid=category_gid,
                )
                product = graphql_client.create_product(product_input)
            else:
                raise

        product_gid = str(product.get("id") or "")
        numeric_product_id = gid_to_numeric_id(product_gid)
        variant_lookup: Dict[object, int] = {}
        for variant in (product.get("variants") or {}).get("nodes") or []:
            variant_id = str(variant.get("id", ""))
            m = re.search(r"(\d+)$", variant_id)
            numeric_variant_id = int(m.group(1)) if m else None
            selected = variant.get("selectedOptions", [])
            if effective_sizes:
                key = tuple(str(i.get("value", "")).strip() for i in selected)
                if len(key) == 2 and numeric_variant_id is not None:
                    variant_lookup[key] = numeric_variant_id
            else:
                key = next((str(i.get("value", "")).strip() for i in selected if i.get("name") == "Color"), "")
                if key and numeric_variant_id is not None:
                    variant_lookup[key] = numeric_variant_id

        # --- STEP 2: Attempt to link options to metafields via productOptionUpdate ---
        # We resolve metaobject GIDs and try linking after the product exists.
        # productOptionsCreate with linkedMetafieldValue has a Shopify bug causing false
        # "duplicate option value" errors, so we use productOptionUpdate instead.
        unique_colors = sorted({img.color_display for img in images}, key=lambda v: v.lower())
        color_name_to_gid: Dict[str, str] = {}
        size_name_to_gid: Dict[str, str] = {}

        if use_swatches_enabled:
            try:
                color_name_to_gid = graphql_client.ensure_option_value_link_targets(
                    namespace=swatch_namespace, key=swatch_key,
                    option_name="Color", value_names=unique_colors,
                )
            except Exception as exc:
                print(f"  Note: could not resolve Color swatch metaobjects: {exc}")

        if size_namespace and size_key and effective_sizes:
            try:
                size_name_to_gid = graphql_client.ensure_option_value_link_targets(
                    namespace=size_namespace, key=size_key,
                    option_name="Size", value_names=effective_sizes,
                )
            except Exception as exc:
                print(f"  Note: could not resolve Size metaobjects: {exc}")

        if color_name_to_gid or size_name_to_gid:
            product_options = product.get("options") or []
            if color_name_to_gid:
                color_option = next((o for o in product_options if o.get("name") == "Color"), None)
                if color_option:
                    color_ov = [ov for ov in (color_option.get("optionValues") or []) if ov.get("id") and ov.get("name")]
                    if len(color_ov) == len(unique_colors):
                        try:
                            graphql_client.update_product_option_link(
                                product_id=product_gid,
                                option_id=color_option["id"],
                                option_name="Color",
                                namespace=swatch_namespace,
                                key=swatch_key,
                                name_to_gid=color_name_to_gid,
                                option_values=color_ov,
                            )
                            print(f"  Linked Color option to {swatch_namespace}.{swatch_key}.")
                        except Exception as exc:
                            print(f"  Note: Color swatch linking failed: {exc}")
            if size_name_to_gid:
                size_option = next((o for o in product_options if o.get("name") == "Size"), None)
                if size_option:
                    size_ov = [ov for ov in (size_option.get("optionValues") or []) if ov.get("id") and ov.get("name")]
                    if len(size_ov) == len(effective_sizes or []):
                        try:
                            graphql_client.update_product_option_link(
                                product_id=product_gid,
                                option_id=size_option["id"],
                                option_name="Size",
                                namespace=size_namespace,
                                key=size_key,
                                name_to_gid=size_name_to_gid,
                                option_values=size_ov,
                            )
                            print(f"  Linked Size option to {size_namespace}.{size_key}.")
                        except Exception as exc:
                            print(f"  Note: Size linking failed: {exc}")

        print(f"  Created Shopify product ID: {numeric_product_id}")
        for img in images:
            uploaded = rest_client.upload_product_image(
                product_id=numeric_product_id,
                file_path=img.file_path,
                alt_text=f"{img.artwork_display} - {img.style_label} - {img.color_display}",
            )
            image_id = uploaded["id"]
            if effective_sizes:
                linked_variant_ids: List[int] = []
                for size in effective_sizes:
                    variant_id = variant_lookup.get((img.color_display, size))
                    if variant_id:
                        rest_client.set_variant_image(variant_id=variant_id, image_id=image_id)
                        linked_variant_ids.append(variant_id)
                if linked_variant_ids:
                    print(f"  Image linkage summary: {img.file_path.name} -> variants {linked_variant_ids}")
            else:
                variant_id = variant_lookup.get(img.color_display)
                if variant_id:
                    rest_client.set_variant_image(variant_id=variant_id, image_id=image_id)
            moved_to = move_uploaded_file(img.file_path, uploaded_dir)
            print(f"  Moved uploaded file -> '{moved_to}'")

        # Re-assert template suffix after all mutations (productOptionUpdate can cause it to drop)
        template_suffix = product_input.get("templateSuffix")
        if template_suffix:
            try:
                graphql_client.update_product_template(product_gid, template_suffix)
            except Exception as exc:
                print(f"  Note: template suffix re-assertion failed: {exc}")

        # Publish to Online Store channel if product was set to active
        if publish_status and publish_status.upper() == "ACTIVE":
            try:
                graphql_client.publish_product_to_online_store(product_gid)
            except Exception as exc:
                print(f"  Note: Online Store publish failed: {exc}")

        created += 1

    print("\nDone")
    if dry_run:
        print(f"Dry-run complete. Products previewed: {total_products}")
    else:
        print(f"Products created: {created}/{total_products}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create Shopify products with linked Color/Size metafields")
    parser.add_argument("folder_positional", nargs="?", help="Folder containing generated images")
    parser.add_argument("--folder", default=None, help="Folder containing generated images")
    parser.add_argument("--description", default=None, help="Optional description text")
    parser.add_argument("--price", default=None, help="Optional override price")
    parser.add_argument("--vendor", default=None, help="Optional Shopify product vendor")
    parser.add_argument("--dry-run", action="store_true", help="Preview parsing/grouping without creating products")
    parser.add_argument("--product-type-map", default="product_type_map.json", help="Path to JSON lookup for filename style code -> product type label")
    parser.add_argument("--uploaded-dir", default="uploaded", help="Folder to move uploaded images into")
    parser.add_argument("--publish-status", default="draft", choices=["draft", "active"], help="Set Shopify products to draft (default) or active")
    parser.add_argument("--sizes", default=None, help="Comma-separated sizes to create as variants")
    parser.add_argument("--swatch-namespace", default=DEFAULT_SWATCH_NAMESPACE, help="Metafield namespace to link Color values to (empty to disable)")
    parser.add_argument("--swatch-key", default=DEFAULT_SWATCH_KEY, help="Metafield key to link Color values to (empty to disable)")
    parser.add_argument("--size-namespace", default="", help="Metafield namespace to link Size values to (empty to disable)")
    parser.add_argument("--size-key", default="", help="Metafield key to link Size values to (empty to disable)")
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
        groups = build_groups(parsed_images)
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
    size_namespace = args.size_namespace.strip() if args.size_namespace else ""
    size_key = args.size_key.strip() if args.size_key else ""
    if not swatch_namespace or not swatch_key:
        swatch_namespace = None
        swatch_key = None
    if not size_namespace or not size_key:
        size_namespace = None
        size_key = None

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
            size_namespace=size_namespace,
            size_key=size_key,
        )
    except Exception as exc:
        print(f"Error during Shopify upload: {exc}")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
