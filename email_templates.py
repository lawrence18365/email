"""
Professional Email Templates for RateTapMX

Enterprise SAAS-style email formatting with staff signatures.
"""

# Staff signatures for each inbox
STAFF_SIGNATURES = {
    "camila@ratetapmx.com": {
        "name": "Camila Rodriguez",
        "title": "Business Development Manager",
        "phone": "+52 55 1234 5678",
        "calendly": "https://calendly.com/camila-ratetapmx/30min",
        "photo": "https://ui-avatars.com/api/?name=Camila+Rodriguez&background=0D6EFD&color=fff&size=80",
    },
    "madison@ratetapmx.com": {
        "name": "Madison Chen",
        "title": "Senior Account Executive",
        "phone": "+52 55 2345 6789",
        "calendly": "https://calendly.com/madison-ratetapmx/30min",
        "photo": "https://ui-avatars.com/api/?name=Madison+Chen&background=198754&color=fff&size=80",
    },
    "valeria@ratetapmx.com": {
        "name": "Valeria Santos",
        "title": "Customer Success Manager",
        "phone": "+52 55 3456 7890",
        "calendly": "https://calendly.com/valeria-ratetapmx/30min",
        "photo": "https://ui-avatars.com/api/?name=Valeria+Santos&background=6F42C1&color=fff&size=80",
    },
}

# Default signature for unknown inboxes
DEFAULT_SIGNATURE = {
    "name": "RateTapMX Team",
    "title": "Customer Success",
    "phone": "+52 55 1234 5678",
    "calendly": "https://calendly.com/ratetapmx/30min",
    "photo": "https://ui-avatars.com/api/?name=RateTapMX&background=0D6EFD&color=fff&size=80",
}


def get_staff_signature(inbox_email: str) -> dict:
    """Get the staff signature for an inbox email."""
    return STAFF_SIGNATURES.get(inbox_email, DEFAULT_SIGNATURE)


def wrap_email_html(body_text: str, inbox_email: str, include_unsubscribe: bool = True) -> str:
    """
    Wrap email body in professional SAAS-style HTML template.

    Args:
        body_text: The email body content (can be plain text or HTML)
        inbox_email: The sender's email address (to determine signature)
        include_unsubscribe: Whether to include unsubscribe footer

    Returns:
        Fully formatted HTML email
    """
    sig = get_staff_signature(inbox_email)

    # Convert plain text line breaks to HTML if needed
    if '<p>' not in body_text and '<br' not in body_text:
        body_html = body_text.replace('\n\n', '</p><p>').replace('\n', '<br>')
        body_html = f'<p>{body_html}</p>'
    else:
        body_html = body_text

    html = f'''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>RateTapMX</title>
</head>
<body style="margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif; font-size: 15px; line-height: 1.6; color: #333333; background-color: #f5f5f5;">
    <table role="presentation" cellspacing="0" cellpadding="0" border="0" width="100%" style="background-color: #f5f5f5;">
        <tr>
            <td style="padding: 30px 20px;">
                <table role="presentation" cellspacing="0" cellpadding="0" border="0" width="600" style="margin: 0 auto; background-color: #ffffff; border-radius: 8px; box-shadow: 0 2px 8px rgba(0,0,0,0.05);">

                    <!-- Email Body -->
                    <tr>
                        <td style="padding: 40px 40px 20px 40px;">
                            <div style="color: #333333; font-size: 15px; line-height: 1.7;">
                                {body_html}
                            </div>
                        </td>
                    </tr>

                    <!-- Signature -->
                    <tr>
                        <td style="padding: 20px 40px 40px 40px;">
                            <table role="presentation" cellspacing="0" cellpadding="0" border="0">
                                <tr>
                                    <td style="vertical-align: top; padding-right: 15px;">
                                        <img src="{sig['photo']}" alt="{sig['name']}" width="60" height="60" style="border-radius: 50%; display: block;">
                                    </td>
                                    <td style="vertical-align: top;">
                                        <p style="margin: 0 0 2px 0; font-weight: 600; color: #333333; font-size: 15px;">{sig['name']}</p>
                                        <p style="margin: 0 0 8px 0; color: #666666; font-size: 13px;">{sig['title']}</p>
                                        <p style="margin: 0; font-size: 13px;">
                                            <a href="tel:{sig['phone']}" style="color: #0D6EFD; text-decoration: none;">{sig['phone']}</a>
                                        </p>
                                        <p style="margin: 4px 0 0 0;">
                                            <a href="{sig['calendly']}" style="display: inline-block; padding: 6px 14px; background-color: #0D6EFD; color: #ffffff; text-decoration: none; border-radius: 4px; font-size: 12px; font-weight: 500;">Book a Call</a>
                                        </p>
                                    </td>
                                </tr>
                            </table>
                        </td>
                    </tr>

                    <!-- Company Footer -->
                    <tr>
                        <td style="padding: 20px 40px; background-color: #f8f9fa; border-top: 1px solid #e9ecef; border-radius: 0 0 8px 8px;">
                            <table role="presentation" cellspacing="0" cellpadding="0" border="0" width="100%">
                                <tr>
                                    <td style="text-align: center;">
                                        <p style="margin: 0 0 8px 0;">
                                            <span style="font-weight: 700; color: #0D6EFD; font-size: 16px;">RateTapMX</span>
                                        </p>
                                        <p style="margin: 0 0 4px 0; color: #666666; font-size: 12px;">
                                            Helping restaurants get more 5-star reviews on autopilot
                                        </p>
                                        <p style="margin: 0; color: #999999; font-size: 11px;">
                                            <a href="https://ratetapmx.com" style="color: #0D6EFD; text-decoration: none;">ratetapmx.com</a>
                                        </p>
                                    </td>
                                </tr>
                            </table>
                        </td>
                    </tr>

                </table>

                <!-- Unsubscribe Footer -->
                {f"""
                <table role="presentation" cellspacing="0" cellpadding="0" border="0" width="600" style="margin: 0 auto;">
                    <tr>
                        <td style="padding: 20px 40px; text-align: center;">
                            <p style="margin: 0; color: #999999; font-size: 11px;">
                                You're receiving this because we help restaurants manage their online reviews.
                                <br>
                                <a href="#unsubscribe" style="color: #999999; text-decoration: underline;">Unsubscribe</a> &nbsp;|&nbsp;
                                <a href="https://ratetapmx.com/privacy" style="color: #999999; text-decoration: underline;">Privacy Policy</a>
                            </p>
                        </td>
                    </tr>
                </table>
                """ if include_unsubscribe else ""}

            </td>
        </tr>
    </table>
</body>
</html>'''

    return html


def get_plain_text_signature(inbox_email: str) -> str:
    """Get plain text version of signature."""
    sig = get_staff_signature(inbox_email)
    return f"""
--
{sig['name']}
{sig['title']}
RateTapMX

{sig['phone']}
Book a call: {sig['calendly']}
https://ratetapmx.com
"""
