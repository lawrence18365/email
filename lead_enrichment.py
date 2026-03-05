"""
Lead Enrichment Service — Wedding Counselors Directory

Enriches leads with practice data and generates personalized email openers.
Uses Jina AI for web scraping (free) and OpenRouter for AI analysis.

Cost: ~$0.39 total for all 633 leads using Gemini Flash.
"""

import os
import re
import json
import time
import logging
import requests
from datetime import datetime, UTC
from typing import Dict, Optional
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# API Keys
OPENROUTER_API_KEY = os.getenv('OPENROUTER_API_KEY')
JINA_API_KEY = os.getenv('JINA_API_KEY')

# Use the same model as the rest of the pipeline
OPENROUTER_API_URL = "https://openrouter.ai/api/v1/chat/completions"
ENRICHMENT_MODEL = os.getenv('AI_MODEL', 'google/gemini-2.0-flash-001')

# Social media / directory domains to skip scraping
SKIP_DOMAINS = (
    'facebook.com', 'fb.com', 'instagram.com', 'tiktok.com',
    'twitter.com', 'x.com', 'linkedin.com', 'youtube.com',
    'pinterest.com', 'reddit.com', 'yelp.com', 'google.com',
    'bdir.in', 'psychologytoday.com', 'goodtherapy.org',
    'therapyden.com', 'zencare.co', 'betterhelp.com',
    'journals.plos.org',
)


class LeadEnrichmentService:
    """
    Enriches counselor/therapist leads with practice data and personalized openers.

    Pipeline:
    1. Scrape practice website (Jina AI — free)
    2. Analyze with AI to extract specialties, services, approach
    3. Generate a personalized email opener referencing something specific
    """

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'
        })

    def enrich_lead(self, lead) -> Dict:
        """Full enrichment pipeline for a lead."""
        logger.info(f"Enriching lead: {lead.email} ({lead.company})")

        enrichment = {
            "success": False,
            "industry": None,
            "company_size": None,
            "company_description": None,
            "linkedin_url": None,
            "recent_news": None,
            "pain_points": None,
            "personalized_opener": None,
            "raw_data": {}
        }

        try:
            # Skip social media / directory URLs — mark as enriched so they
            # don't keep re-entering the queue every cron run
            website = lead.website or ''
            if any(d in website.lower() for d in SKIP_DOMAINS):
                logger.info(f"Skipping {lead.email} — social/directory URL (marking enriched)")
                enrichment["skipped_social"] = True
                return enrichment

            # Step 1: Scrape practice website
            website_content = None
            if website:
                website_content = self._scrape_website(website)
                if website_content:
                    enrichment["raw_data"]["website_content"] = website_content[:2000]

            if not website_content:
                logger.info(f"No website content for {lead.email}")
                return enrichment

            # Step 2: Analyze + generate opener in a single AI call (saves cost)
            if OPENROUTER_API_KEY:
                result = self._analyze_and_generate(
                    company_name=lead.company or '',
                    website_content=website_content,
                    lead_name=lead.first_name or 'there',
                    website_url=website
                )
                if result:
                    enrichment.update(result)
                    enrichment["success"] = True

        except Exception as e:
            logger.error(f"Enrichment failed for {lead.email}: {str(e)}")
            enrichment["error"] = str(e)

        return enrichment

    def _scrape_website(self, url: str) -> Optional[str]:
        """Scrape website using Jina AI Reader (free tier)."""
        try:
            if not url.startswith('http'):
                url = f"https://{url}"

            jina_url = f"https://r.jina.ai/{url}"
            headers = {"Accept": "text/plain"}
            if JINA_API_KEY:
                headers["Authorization"] = f"Bearer {JINA_API_KEY}"

            response = self.session.get(jina_url, headers=headers, timeout=30)

            if response.status_code == 200:
                content = response.text
                content = re.sub(r'\s+', ' ', content)
                return content[:5000]

        except Exception as e:
            logger.debug(f"Website scrape failed for {url}: {str(e)}")

        return None

    def _call_ai(self, system: str, prompt: str, max_tokens: int = 800) -> Optional[str]:
        """Call OpenRouter API."""
        if not OPENROUTER_API_KEY:
            logger.warning("OpenRouter API key not configured")
            return None

        try:
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                "HTTP-Referer": "https://weddingcounselors.com",
                "X-Title": "WeddingCounselors Lead Enrichment"
            }

            payload = {
                "model": ENRICHMENT_MODEL,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": prompt}
                ],
                "temperature": 0.7,
                "max_tokens": max_tokens
            }

            response = self.session.post(
                OPENROUTER_API_URL,
                headers=headers,
                json=payload,
                timeout=60
            )

            if response.status_code == 200:
                data = response.json()
                if data.get("choices") and len(data["choices"]) > 0:
                    return data["choices"][0]["message"]["content"]
            else:
                logger.error(f"OpenRouter API error: {response.status_code} - {response.text[:200]}")

        except Exception as e:
            logger.error(f"OpenRouter API call failed: {str(e)}")

        return None

    def _analyze_and_generate(self, company_name: str, website_content: str,
                               lead_name: str, website_url: str) -> Optional[Dict]:
        """Single AI call: analyze practice AND generate a personalized question.

        The question is used as the opening of a conversation-first email.
        It should tap into their professional identity and make them WANT to reply.
        Cialdini principles: Liking (genuine interest) + Commitment (small ask).
        """

        system = """You are analyzing a marriage counselor / therapist / wedding officiant's website.
Your goal: craft a genuine, specific QUESTION about their practice that would make them
want to reply. This is for a conversational outreach email — NOT a sales pitch.

The question must:
- Reference something SPECIFIC from their website (their modality, niche, approach)
- Be a question they'd actually enjoy answering (therapists love discussing their methods)
- Sound like it comes from someone genuinely curious about their work
- Be 1-2 sentences max, ending with a question mark
- NOT mention any directory, product, or service
- NOT be generic ("do you enjoy your work?" is terrible)"""

        prompt = f"""Analyze this counselor/therapist's website and provide a JSON response.

BUSINESS NAME: {company_name}
WEBSITE: {website_url}

WEBSITE CONTENT:
{website_content}

Return ONLY valid JSON with these fields:
{{
  "industry": "their primary specialty (e.g., 'Marriage Counseling', 'Premarital Counseling', 'Wedding Officiant', 'Family Therapy', 'Couples Therapy')",
  "company_description": "1-2 sentence summary of their practice and therapeutic approach",
  "company_size": "estimated practice size: 'Solo Practice', '2-5', '6-10', '10+'",
  "pain_points": "2-3 specific challenges this practice might face with online visibility or getting couples to find them",
  "personalized_opener": "A specific, genuine QUESTION for {lead_name} about their practice that references something from their website. The question should tap into their expertise and make them want to reply. Examples of GOOD questions: 'I noticed you use a Gottman-based approach with couples — do you find that couples who specifically seek out evidence-based therapy tend to be more committed to the process?' or 'I saw you offer intensive weekend retreats for couples — are you seeing more demand for that format vs traditional weekly sessions?' or 'Your work with military couples really stood out — do most of those couples find you through base referrals, or are they searching online?' BAD questions (too generic): 'Do you enjoy working with couples?' or 'How is your practice doing?' or 'What services do you offer?' The question MUST reference something specific you found on their site."
}}

Return ONLY the JSON. No other text."""

        try:
            result = self._call_ai(system, prompt)
            if result:
                json_match = re.search(r'\{[\s\S]*\}', result)
                if json_match:
                    parsed = json.loads(json_match.group())
                    # Clean up opener
                    opener = parsed.get('personalized_opener', '')
                    if opener:
                        opener = opener.strip().strip('"\'').strip()
                        opener = re.sub(r'^(Here\'s|Here is)[^:]*:\s*', '', opener, flags=re.IGNORECASE)
                        parsed['personalized_opener'] = opener
                    return parsed

        except Exception as e:
            logger.error(f"AI analysis failed: {str(e)}")

        return None


def enrich_lead_in_db(app, db, lead_id: int) -> bool:
    """Enrich a lead and save to database."""
    from models import Lead

    with app.app_context():
        lead = db.session.get(Lead, lead_id)
        if not lead:
            logger.error(f"Lead {lead_id} not found")
            return False

        if lead.enriched:
            logger.info(f"Lead {lead_id} already enriched")
            return True

        service = LeadEnrichmentService()
        enrichment = service.enrich_lead(lead)

        if enrichment.get("success"):
            lead.enriched = True
            lead.enriched_at = datetime.now(UTC)
            lead.industry = enrichment.get("industry")
            lead.company_size = enrichment.get("company_size")
            lead.company_description = enrichment.get("company_description")
            lead.recent_news = enrichment.get("recent_news")
            pain_points = enrichment.get("pain_points")
            if isinstance(pain_points, list):
                lead.pain_points = "; ".join(pain_points)
            else:
                lead.pain_points = pain_points
            lead.personalized_opener = enrichment.get("personalized_opener")
            lead.enrichment_data = json.dumps(enrichment.get("raw_data", {}))

            db.session.commit()
            logger.info(f"Lead {lead_id} enriched successfully")
            return True
        elif enrichment.get("skipped_social"):
            # Mark social/directory leads as enriched so they don't
            # re-enter the queue every cron run
            lead.enriched = True
            lead.enriched_at = datetime.now(UTC)
            db.session.commit()
            logger.info(f"Lead {lead_id} marked enriched (social/directory URL — no data to scrape)")
            return True
        else:
            logger.warning(f"Lead {lead_id} enrichment returned no data")
            return False


def enrich_all_unenriched_leads(app, db, limit: int = 50) -> Dict:
    """Enrich all leads that haven't been enriched yet."""
    from models import Lead

    results = {
        "processed": 0,
        "enriched": 0,
        "failed": 0,
        "skipped": 0
    }

    with app.app_context():
        leads = Lead.query.filter(
            Lead.enriched == False,
            Lead.website.isnot(None),
            Lead.website != '',
            Lead.status.in_(['new', 'contacted'])
        ).limit(limit).all()

        for lead in leads:
            results["processed"] += 1

            if enrich_lead_in_db(app, db, lead.id):
                results["enriched"] += 1
            else:
                results["failed"] += 1

            # Small delay to avoid rate limiting
            time.sleep(1)

    logger.info(f"Enrichment batch complete: {results}")
    return results


if __name__ == '__main__':
    import sys
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from app import app
    from models import db

    import argparse
    parser = argparse.ArgumentParser(description='Enrich leads with website data')
    parser.add_argument('--limit', type=int, default=50, help='Max leads to process')
    parser.add_argument('--lead-id', type=int, help='Enrich a specific lead by ID')
    parser.add_argument('--dry-run', action='store_true', help='Preview enrichment for 3 leads without saving')
    args = parser.parse_args()

    if args.lead_id:
        enrich_lead_in_db(app, db, args.lead_id)
    elif args.dry_run:
        from models import Lead
        service = LeadEnrichmentService()
        with app.app_context():
            leads = Lead.query.filter(
                Lead.enriched == False,
                Lead.website.isnot(None),
                Lead.website != '',
                Lead.status.in_(['new', 'contacted'])
            ).limit(3).all()
            for lead in leads:
                print(f"\n{'='*60}")
                print(f"Lead: {lead.email} | {lead.company}")
                print(f"Website: {lead.website}")
                result = service.enrich_lead(lead)
                if result.get('success'):
                    print(f"Industry: {result.get('industry')}")
                    print(f"Description: {result.get('company_description')}")
                    print(f"OPENER: {result.get('personalized_opener')}")
                else:
                    print("FAILED — no data returned")
                print(f"{'='*60}")
                time.sleep(1)
    else:
        results = enrich_all_unenriched_leads(app, db, limit=args.limit)
        print(f"Results: {results}")
