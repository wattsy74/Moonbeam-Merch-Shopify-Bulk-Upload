import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("shopify_bulk_upload", ROOT / "shopify_bulk_upload.py")
module = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(module)


def test_create_product_payload_defaults_to_draft():
    client = module.ShopifyClient.__new__(module.ShopifyClient)
    payload = None

    def fake_request(method, endpoint, json_data=None):
        nonlocal payload
        payload = json_data
        return {"product": {"id": 1, "variants": []}}

    client._request = fake_request
    client.create_product(
        title="Test",
        body_html="<p>Body</p>",
        vendor="Moonbeam Merch",
        tags="tag",
        template_suffix=None,
        product_type=None,
        variants=[{"option1": "Red", "sku": "SKU1", "price": "10.00"}],
        publish_status="draft",
    )
    assert payload["product"]["status"] == "draft"
