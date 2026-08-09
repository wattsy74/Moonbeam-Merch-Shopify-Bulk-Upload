import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from shopify_bulk_upload import ParsedImage, ProductTypeConfig, parse_filename
from shopify_bulk_upload_graphql import GraphQLShopifyClient, build_graphql_product_input, create_products


class BuildGraphQLProductInputTests(unittest.TestCase):
    def test_links_color_and_size_option_values_to_metafields(self):
        image = ParsedImage(
            file_path=Path("/tmp/demo.png"),
            artwork_raw="Jessie",
            artwork_display="Jessie",
            code_ab="PBM0",
            code_c="C005",
            sku="PBM0_STTU169_C005",
            style_code="STTU169",
            style_label="Creator_2.0",
            style_price="24.99",
            style_template_suffix="clothing-template",
            style_product_type="T-Shirts",
            style_description="Demo",
            style_sizes=["S", "M"],
            style_size_prices={"S": "24.99", "M": "24.99"},
            style_category=None,
            color_raw="CottonPink",
            color_display="Cotton Pink",
        )

        payload = build_graphql_product_input(
            images=[image],
            title="Demo",
            description=None,
            vendor="Moonbeam Merch",
            tags="Demo",
            publish_status="draft",
            sizes=["S", "M"],
            price_override=None,
            swatch_namespace="shopify",
            swatch_key="color-pattern",
            size_namespace="shopify",
            size_key="size",
            use_swatches=True,
        )

        color_option = next(opt for opt in payload["productOptions"] if opt["name"] == "Color")
        self.assertNotIn("linkedMetafield", color_option)
        self.assertEqual(color_option["values"][0]["name"], "Cotton Pink")

        size_option = next(opt for opt in payload["productOptions"] if opt["name"] == "Size")
        self.assertNotIn("linkedMetafield", size_option)
        self.assertEqual(size_option["values"][0]["name"], "S")

        first_variant = payload["variants"][0]
        self.assertEqual(first_variant["optionValues"][0]["name"], "Cotton Pink")
        self.assertEqual(first_variant["optionValues"][1]["name"], "S")
        self.assertNotIn("linkedMetafieldValue", first_variant["optionValues"][0])

    def test_parse_filename_uses_color_in_generated_sku(self):
        product_type_map = {
            "BabyCreator": ProductTypeConfig(
                label="Baby T-Shirt",
                price="10.99",
                template_suffix="clothing-template",
                product_type="T-Shirts",
                description=None,
                sizes=["0-6"],
                size_prices={"0-6": "10.99"},
                category=None,
            )
        }

        white_image = parse_filename(Path("/tmp/Jessie_PFM0_STTB918_C001_BabyCreator_White.png"), product_type_map)
        black_image = parse_filename(Path("/tmp/Jessie_PFM0_STTB918_C002_BabyCreator_Black.png"), product_type_map)

        self.assertNotEqual(white_image.sku, black_image.sku)
        self.assertIn("White", white_image.sku)
        self.assertIn("Black", black_image.sku)

    def test_option_value_link_targets_use_storefront_access_only(self):
        client = GraphQLShopifyClient.__new__(GraphQLShopifyClient)
        client.get_metaobject_definition_by_type = Mock(return_value=None)
        client.create_metaobject_definition = Mock(return_value={"id": "gid://shopify/MetaobjectDefinition/1"})
        client.get_metafield_definition = Mock(return_value=None)
        client.create_metafield_definition = Mock(return_value={"id": "gid://shopify/MetafieldDefinition/1"})
        client.get_metaobject_definition_by_id = Mock(return_value=None)
        client.list_metaobjects_by_type = Mock(return_value=[])
        client.create_metaobject = Mock(return_value={"id": "gid://shopify/Metaobject/1"})

        client.ensure_option_value_link_targets("custom", "color-swatch", "Color", ["White"])

        payload = client.create_metaobject_definition.call_args.args[0]
        self.assertEqual(payload["access"], {"storefront": "PUBLIC_READ"})
        self.assertNotIn("admin", payload["access"])

    def test_creates_products_using_numeric_product_id_for_image_uploads(self):
        image_path = Path("/tmp/demo.png")
        image_path.write_bytes(b"demo")
        image = ParsedImage(
            file_path=image_path,
            artwork_raw="Jessie",
            artwork_display="Jessie",
            code_ab="PBM0",
            code_c="C005",
            sku="PBM0_STTU169_C005",
            style_code="STTU169",
            style_label="Creator_2.0",
            style_price="24.99",
            style_template_suffix="clothing-template",
            style_product_type="T-Shirts",
            style_description="Demo",
            style_sizes=["S"],
            style_size_prices={"S": "24.99"},
            style_category=None,
            color_raw="CottonPink",
            color_display="Cotton Pink",
        )

        graphql_client = Mock()
        graphql_client.create_product.return_value = {
            "id": "gid://shopify/Product/123456",
            "options": [
                {"id": "gid://shopify/ProductOption/1", "name": "Color", "optionValues": [{"id": "gid://shopify/ProductOptionValue/10", "name": "Cotton Pink"}]},
                {"id": "gid://shopify/ProductOption/2", "name": "Size", "optionValues": [{"id": "gid://shopify/ProductOptionValue/20", "name": "S"}]},
            ],
            "variants": {"nodes": [{"id": "gid://shopify/ProductVariant/999", "selectedOptions": [{"name": "Color", "value": "Cotton Pink"}, {"name": "Size", "value": "S"}]}]},
        }
        graphql_client.ensure_option_value_link_targets.side_effect = [
            {"cotton pink": "gid://shopify/Metaobject/1"},
            {"s": "gid://shopify/Metaobject/2"},
        ]
        graphql_client.update_product_option_link.return_value = {}
        rest_client = Mock()
        rest_client.upload_product_image.return_value = {"id": 987}
        rest_client.set_variant_image.return_value = {}

        with patch("shopify_bulk_upload_graphql.build_product_tags", return_value="Demo"), \
             patch("shopify_bulk_upload_graphql.choose_title", return_value="Demo"), \
             patch("shopify_bulk_upload_graphql.move_uploaded_file", return_value=str(image_path)), \
             patch("shopify_bulk_upload_graphql.build_graphql_product_input") as build_input:
            build_input.return_value = {
                "title": "Demo",
                "descriptionHtml": "Demo",
                "productOptions": [{"name": "Color", "values": [{"name": "Cotton Pink"}]}],
                "variants": [{"optionValues": [{"optionName": "Color", "name": "Cotton Pink"}], "sku": "demo", "price": "24.99"}],
                "tags": "Demo",
                "templateSuffix": "clothing-template",
                "productType": "T-Shirts",
                "status": "DRAFT",
            }

            create_products(
                graphql_client=graphql_client,
                rest_client=rest_client,
                groups={("Jessie", "Creator_2.0"): [image]},
                description=None,
                price_override=None,
                vendor="Moonbeam Merch",
                uploaded_dir=Path("/tmp"),
                dry_run=False,
                publish_status="draft",
                sizes=["S"],
                swatch_namespace="shopify",
                swatch_key="color-pattern",
                size_namespace="shopify",
                size_key="size",
            )

        rest_client.upload_product_image.assert_called_once_with(
            product_id=123456,
            file_path=image_path,
            alt_text="Jessie - Creator_2.0 - Cotton Pink",
        )


if __name__ == "__main__":
    unittest.main()
