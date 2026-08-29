import os
from urllib.parse import urlparse

import requests


class InstagramPublishingError(Exception):
    pass


def _get_config():
    return {
        "access_token": (os.getenv("META_ACCESS_TOKEN") or "").strip(),
        "instagram_user_id": (os.getenv("META_IG_USER_ID") or "").strip(),
        "graph_version": (os.getenv("META_GRAPH_VERSION") or "v23.0").strip(),
        "graph_base_url": (os.getenv("META_GRAPH_BASE_URL") or "https://graph.facebook.com").rstrip("/"),
    }


def instagram_publishing_configured():
    config = _get_config()
    return bool(
        config["access_token"]
        and config["instagram_user_id"]
    )


def _validate_media_url(media_url):
    if not media_url:
        raise InstagramPublishingError(
            "Instagram publishing requires a public image URL."
        )

    parsed = urlparse(media_url)

    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise InstagramPublishingError(
            "The Instagram media URL must be a public http/https URL."
        )


def _parse_meta_response(response, action):
    try:
        data = response.json()
    except Exception:
        data = {}

    if response.ok:
        return data

    error = data.get("error", {}) if isinstance(data, dict) else {}
    message = error.get("message") or response.text or "Unknown Meta API error"

    raise InstagramPublishingError(
        f"{action} failed: {message}"
    )


def publish_instagram_content(caption, media_url):
    """
    Publish one image post to Instagram using Meta's publishing flow.

    Credentials are intentionally read from environment variables so no
    access token is stored in the BizFlow database or GitHub repository.

    Required once Meta verification is complete:
      META_ACCESS_TOKEN
      META_IG_USER_ID

    Optional:
      META_GRAPH_VERSION
      META_GRAPH_BASE_URL
    """
    config = _get_config()

    if not instagram_publishing_configured():
        raise InstagramPublishingError(
            "Meta publishing is not connected yet. Add META_ACCESS_TOKEN and META_IG_USER_ID after Meta verification."
        )

    _validate_media_url(media_url)

    user_id = config["instagram_user_id"]
    token = config["access_token"]
    base = config["graph_base_url"]
    version = config["graph_version"]

    create_url = f"{base}/{version}/{user_id}/media"

    create_response = requests.post(
        create_url,
        data={
            "image_url": media_url,
            "caption": caption or "",
            "access_token": token,
        },
        timeout=45,
    )

    create_data = _parse_meta_response(
        create_response,
        "Instagram media container creation"
    )

    creation_id = create_data.get("id")

    if not creation_id:
        raise InstagramPublishingError(
            "Meta did not return a media creation ID."
        )

    publish_url = f"{base}/{version}/{user_id}/media_publish"

    publish_response = requests.post(
        publish_url,
        data={
            "creation_id": creation_id,
            "access_token": token,
        },
        timeout=45,
    )

    publish_data = _parse_meta_response(
        publish_response,
        "Instagram media publishing"
    )

    post_id = publish_data.get("id")

    if not post_id:
        raise InstagramPublishingError(
            "Meta did not return a published Instagram post ID."
        )

    return str(post_id)
