#!/usr/bin/env python3
"""
Find restaurant leads for RateTap - Restaurant Review Revolution
Uses DuckDuckGo (no API limits) + direct scraping
"""

import os
import re
import time
import requests
from urllib.parse import quote_plus, urlparse
from dotenv import load_dotenv
from app import app, db
from models import Lead

load_dotenv()

JINA_API_KEY = os.getenv('JINA_API_KEY')
EMAIL_PATTERN = re.compile(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}', re.IGNORECASE)
EXCLUDE = ['noreply', 'no-reply', 'support@', 'info@', 'admin@', 'hello@',
           'contact@', 'example.com', 'test.com', 'wixpress', 'sentry', 'cloudflare',
           'google.com', 'facebook.com', 'instagram.com', 'twitter.com', 'linkedin.com',
           '.gov', '.edu', 'yelp.com', 'tripadvisor', 'opentable']

session = requests.Session()
session.headers.update({
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Accept-Language': 'en-US,en;q=0.5',
})

def log(msg):
    print(msg, flush=True)

def duckduckgo_search(query, num_results=10):
    """Search using DuckDuckGo HTML - completely free"""
    try:
        url = f"https://html.duckduckgo.com/html/?q={quote_plus(query)}"
        response = session.get(url, timeout=15)
        if response.status_code == 200:
            # Extract URLs from result links
            urls = re.findall(r'href="(https?://[^"]+)"', response.text)
            # Filter out DuckDuckGo internal links
            urls = [u for u in urls if 'duckduckgo.com' not in u
                   and 'bing.com' not in u
                   and 'yahoo.com' not in u]
            return list(dict.fromkeys(urls))[:num_results]  # Dedupe
    except Exception as e:
        log(f"  DuckDuckGo error: {e}")
    return []

def scrape_emails_direct(url):
    """Scrape emails directly from URL"""
    emails = set()
    try:
        response = session.get(url, timeout=10, allow_redirects=True)
        if response.status_code == 200:
            text = response.text

            # Find emails in page
            for match in EMAIL_PATTERN.findall(text):
                email = match.lower().strip()
                if not any(ex in email for ex in EXCLUDE):
                    # Extra validation
                    domain = email.split('@')[1] if '@' in email else ''
                    if '.' in domain and len(domain) > 4:
                        emails.add(email)

            # Also check for mailto: links
            mailto = re.findall(r'mailto:([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})', text)
            for email in mailto:
                email = email.lower().strip()
                if not any(ex in email for ex in EXCLUDE):
                    emails.add(email)
    except:
        pass
    return emails

def scrape_with_jina(url):
    """Fallback: Scrape using Jina Reader for JS-heavy sites"""
    emails = set()
    if not JINA_API_KEY:
        return emails
    try:
        jina_url = f"https://r.jina.ai/{url}"
        headers = {"Authorization": f"Bearer {JINA_API_KEY}"}
        response = session.get(jina_url, headers=headers, timeout=15)
        if response.status_code == 200:
            for match in EMAIL_PATTERN.findall(response.text):
                email = match.lower().strip()
                if not any(ex in email for ex in EXCLUDE):
                    emails.add(email)
    except:
        pass
    return emails

def guess_name(email):
    local = email.split('@')[0]
    clean = re.sub(r'\d+', '', local)
    if '.' in clean:
        parts = clean.split('.')
        return parts[0].capitalize(), parts[-1].capitalize() if len(parts) > 1 else ''
    elif '_' in clean:
        parts = clean.split('_')
        return parts[0].capitalize(), parts[-1].capitalize() if len(parts) > 1 else ''
    return clean.capitalize(), ''

def domain_to_company(domain):
    name = domain.replace('www.', '')
    name = re.sub(r'\.(com|org|net|io|co|mx|us|ca).*$', '', name)
    return name.replace('-', ' ').replace('_', ' ').title()

# Queries targeting restaurant owners
QUERIES = [
    # Direct contact page searches
    '"restaurant" "owner" "email" site:com',
    '"restaurant group" "contact" email',
    '"restaurant" "general manager" email contact',

    # Specific cities from RateTap testimonials
    'Austin Texas restaurant owner contact email',
    'Seattle restaurant owner contact email',
    'Denver restaurant owner contact email',
    'Vancouver BC restaurant owner email',

    # Mexico market
    'restaurante CDMX dueño email contacto',
    'restaurante Monterrey propietario contacto',

    # Restaurant associations/directories
    'restaurant owners association directory',
    'restaurant business owners network',

    # Multi-location (higher value)
    'restaurant franchise owner contact',
    'restaurant chain regional manager email',
]

def main():
    log("=" * 60)
    log("RateTap Lead Finder - Restaurant Owners")
    log("Using DuckDuckGo (free, unlimited)")
    log("=" * 60)

    all_leads = []
    found_emails = set()
    scraped_domains = set()

    for i, query in enumerate(QUERIES):
        log(f"\n[{i+1}/{len(QUERIES)}] {query}")

        urls = duckduckgo_search(query, num_results=8)
        log(f"  Found {len(urls)} URLs")

        for url in urls:
            # Skip already scraped domains
            domain = urlparse(url).netloc
            if domain in scraped_domains:
                continue
            scraped_domains.add(domain)

            log(f"  -> {url[:55]}...")

            # Try direct scrape first (faster)
            emails = scrape_emails_direct(url)

            # If no emails found and Jina available, try Jina
            if not emails and JINA_API_KEY:
                emails = scrape_with_jina(url)

            for email in emails:
                if email not in found_emails:
                    found_emails.add(email)
                    first, last = guess_name(email)
                    email_domain = email.split('@')[1]

                    lead = {
                        'email': email,
                        'first_name': first,
                        'last_name': last,
                        'company': domain_to_company(email_domain),
                        'website': f"https://{email_domain}",
                        'source': 'ratetap_prospecting'
                    }
                    all_leads.append(lead)
                    log(f"     + {email}")

        time.sleep(0.5)  # Be nice to DuckDuckGo

    log("\n" + "=" * 60)
    log(f"Found {len(all_leads)} unique leads")
    log("=" * 60)

    # Add to database
    if all_leads:
        with app.app_context():
            added = 0
            for lead_data in all_leads:
                existing = Lead.query.filter_by(email=lead_data['email']).first()
                if not existing:
                    lead = Lead(
                        email=lead_data['email'],
                        first_name=lead_data['first_name'],
                        last_name=lead_data['last_name'],
                        company=lead_data['company'],
                        website=lead_data['website'],
                        source=lead_data['source'],
                        status='new'
                    )
                    db.session.add(lead)
                    added += 1
            db.session.commit()

            log(f"\nAdded {added} new leads to CRM database")
            total = Lead.query.count()
            log(f"Total leads now: {total}")

    # Final summary
    log("\n=== ALL LEADS ===")
    for lead in all_leads:
        log(f"  {lead['email']:40} | {lead['company']}")

if __name__ == "__main__":
    main()
