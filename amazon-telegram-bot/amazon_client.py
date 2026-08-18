"""
Client minimale per la Amazon Product Advertising API 5.0 (SearchItems).
Firma le richieste con AWS Signature V4, come richiesto da Amazon.
"""

import os
import json
import datetime
import hashlib
import hmac
import requests

import config


def _sign(key, msg):
    return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).digest()


def _get_signature_key(key, date_stamp, region_name, service_name):
    k_date = _sign(("AWS4" + key).encode("utf-8"), date_stamp)
    k_region = _sign(k_date, region_name)
    k_service = _sign(k_region, service_name)
    k_signing = _sign(k_service, "aws4_request")
    return k_signing


def search_items(keywords, search_index="All", item_count=10):
    """Cerca prodotti su Amazon tramite PA-API 5.0 SearchItems."""

    access_key = os.environ["AMAZON_ACCESS_KEY"]
    secret_key = os.environ["AMAZON_SECRET_KEY"]
    partner_tag = os.environ[config.PARTNER_TAG_ENV]

    host = config.HOST
    region = config.REGION
    service = "ProductAdvertisingAPI"
    endpoint = f"https://{host}/paapi5/searchitems"
    target = "com.amazon.paapi5.v1.ProductAdvertisingAPIv1.SearchItems"

    payload = {
        "Keywords": keywords,
        "SearchIndex": search_index,
        "ItemCount": item_count,
        "PartnerTag": partner_tag,
        "PartnerType": "Associates",
        "Marketplace": config.MARKETPLACE,
        "Resources": [
            "Images.Primary.Large",
            "ItemInfo.Title",
            "Offers.Listings.Price",
            "Offers.Listings.SavingBasis",
            "Offers.Summaries.LowestPrice",
        ],
    }
    payload_json = json.dumps(payload)

    now = datetime.datetime.utcnow()
    amz_date = now.strftime("%Y%m%dT%H%M%SZ")
    date_stamp = now.strftime("%Y%m%d")

    canonical_uri = "/paapi5/searchitems"
    canonical_querystring = ""
    canonical_headers = (
        f"content-encoding:amz-1.0\n"
        f"content-type:application/json; charset=utf-8\n"
        f"host:{host}\n"
        f"x-amz-date:{amz_date}\n"
        f"x-amz-target:{target}\n"
    )
    signed_headers = "content-encoding;content-type;host;x-amz-date;x-amz-target"
    payload_hash = hashlib.sha256(payload_json.encode("utf-8")).hexdigest()
    canonical_request = (
        f"POST\n{canonical_uri}\n{canonical_querystring}\n"
        f"{canonical_headers}\n{signed_headers}\n{payload_hash}"
    )

    algorithm = "AWS4-HMAC-SHA256"
    credential_scope = f"{date_stamp}/{region}/{service}/aws4_request"
    string_to_sign = (
        f"{algorithm}\n{amz_date}\n{credential_scope}\n"
        f"{hashlib.sha256(canonical_request.encode('utf-8')).hexdigest()}"
    )

    signing_key = _get_signature_key(secret_key, date_stamp, region, service)
    signature = hmac.new(
        signing_key, string_to_sign.encode("utf-8"), hashlib.sha256
    ).hexdigest()

    authorization_header = (
        f"{algorithm} Credential={access_key}/{credential_scope}, "
        f"SignedHeaders={signed_headers}, Signature={signature}"
    )

    headers = {
        "content-encoding": "amz-1.0",
        "content-type": "application/json; charset=utf-8",
        "host": host,
        "x-amz-date": amz_date,
        "x-amz-target": target,
        "Authorization": authorization_header,
    }

    response = requests.post(endpoint, headers=headers, data=payload_json, timeout=15)
    response.raise_for_status()
    return response.json()
