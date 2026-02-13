"""
Multi-brand email wrapper. Derives branding from inbox email domain.
"""

from config import Config
from unsubscribe import generate_unsubscribe_token

# Brand registry keyed by email domain
BRANDS = {
    "weddingcounselors.com": {
        "name": "Wedding Counselors Directory",
        "domain": "weddingcounselors.com",
        "tagline": "Connecting engaged couples with trusted premarital counselors",
    },
    "ratetapmx.com": {
        "name": "RateTap",
        "domain": "ratetapmx.com",
        "tagline": "Get more Google reviews with NFC tap cards",
    },
}

DEFAULT_BRAND = BRANDS["weddingcounselors.com"]


def get_brand(inbox_email: str) -> dict:
    """Look up brand config from inbox email domain."""
    domain = inbox_email.split("@")[-1] if inbox_email else ""
    return BRANDS.get(domain, DEFAULT_BRAND)


# Backward-compatible module-level constants (used nowhere else, but safe)
BRAND_NAME = DEFAULT_BRAND["name"]
BRAND_DOMAIN = DEFAULT_BRAND["domain"]
BRAND_TAGLINE = DEFAULT_BRAND["tagline"]


def build_unsubscribe_url(lead) -> str:
    token = generate_unsubscribe_token(lead.id, lead.email)
    base = Config.PUBLIC_BASE_URL.rstrip('/')
    return f"{base}/unsubscribe/{token}"


def wrap_email_html(
    body_text: str,
    inbox_email: str,
    lead=None,
    include_unsubscribe: bool = True
) -> str:
    """
    Wrap email body in a minimal, professional HTML template.

    Args:
        body_text: The email body content (plain text or HTML)
        inbox_email: The sender's email address (reserved for future use)
        lead: Lead model instance for unsubscribe link generation
        include_unsubscribe: Whether to include unsubscribe footer

    Returns:
        Fully formatted HTML email
    """
    # Convert plain text line breaks to HTML if needed
    if '<p>' not in body_text and '<br' not in body_text:
        body_html = body_text.replace('\n\n', '</p><p>').replace('\n', '<br>')
        body_html = f'<p>{body_html}</p>'
    else:
        body_html = body_text

    unsubscribe_html = ""
    if include_unsubscribe:
        if lead is not None:
            unsubscribe_url = build_unsubscribe_url(lead)
            unsubscribe_html = (
                f'If you prefer not to receive emails from us, '
                f'you can <a href="{unsubscribe_url}" style="color:#666666; text-decoration:underline;">unsubscribe</a>.'
            )
        else:
            unsubscribe_html = 'If you prefer not to receive emails from us, reply with "unsubscribe".'

    brand = get_brand(inbox_email)

    html = f'''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{brand["name"]}</title>
</head>
<body style="margin:0; padding:0; background-color:#ffffff;">
    <table role="presentation" cellspacing="0" cellpadding="0" border="0" width="100%" style="background-color:#ffffff;">
        <tr>
            <td style="padding:32px 20px;">
                <table role="presentation" cellspacing="0" cellpadding="0" border="0" width="640" style="margin:0 auto;">
                    <tr>
                        <td style="font-family:-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif; font-size:15px; line-height:1.65; color:#1a1a1a;">
                            {body_html}
                        </td>
                    </tr>
                    <tr>
                        <td style="padding-top:24px; border-top:1px solid #e6e6e6; font-family:-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif; font-size:12px; line-height:1.5; color:#666666;">
                            <div style="font-weight:600; color:#111111;">{brand["name"]}</div>
                            <div style="margin-top:2px;">{brand["tagline"]}</div>
                            <div style="margin-top:2px;">
                                <a href="https://{brand["domain"]}" style="color:#111111; text-decoration:none;">{brand["domain"]}</a>
                            </div>
                            {f'<div style="margin-top:8px;">{unsubscribe_html}</div>' if unsubscribe_html else ''}
                        </td>
                    </tr>
                </table>
            </td>
        </tr>
    </table>
</body>
</html>'''

    return html


def get_plain_text_signature(inbox_email: str) -> str:
    """Get plain text version of signature."""
    brand = get_brand(inbox_email)
    return f"""
--
{brand["name"]}
{brand["domain"]}
"""
