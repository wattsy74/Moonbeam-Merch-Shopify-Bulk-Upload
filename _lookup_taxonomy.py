import os, sys
from dotenv import load_dotenv

load_dotenv(dotenv_path=".env")
shop = os.getenv("SHOPIFY_SHOP_DOMAIN")
token = os.getenv("SHOPIFY_ACCESS_TOKEN")
version = os.getenv("SHOPIFY_API_VERSION", "2026-07")

if not shop or not token:
    print("ERROR: SHOPIFY_SHOP_DOMAIN and SHOPIFY_ACCESS_TOKEN must be set in .env")
    sys.exit(1)

import requests
session = requests.Session()
session.headers.update({"X-Shopify-Access-Token": token, "Content-Type": "application/json"})

search_terms = ["T-Shirts", "Kids T-Shirts", "Baby Tops", "T-Shirt", "Children"]
url = f"https://{shop}/admin/api/{version}/graphql.json"

for term in search_terms:
    query = """
    query($search: String!) {
      taxonomy { categories(first: 5, search: $search) { nodes { id name fullName } } }
    }
    """
    r = session.post(url, json={"query": query, "variables": {"search": term}})
    nodes = r.json().get("data", {}).get("taxonomy", {}).get("categories", {}).get("nodes", [])
    print(f"\nSearch: '{term}'")
    for n in nodes:
        print(f"  GID:  {n['id']}")
        print(f"  Path: {n['fullName']}")
        print()
