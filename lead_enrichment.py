"""
Lead Enrichment Service

Enriches leads with company data and generates personalized email openers.
Uses FREE tools: Jina AI for web scraping, OpenRouter (Llama 3.1 405B) for AI analysis.
"""

import os
import re
import json
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

# OpenRouter API (FREE Google Gemma 3 12B)
OPENROUTER_API_URL = "https://openrouter.ai/api/v1/chat/completions"
OPENROUTER_MODEL = "google/gemma-3-12b-it:free"


class LeadEnrichmentService:
    """
    Enriches leads with company data and generates personalized openers.

    Pipeline:
    1. Scrape company website (using Jina AI - FREE)
    2. Search for recent news
    3. Analyze with AI to extract structured data
    4. Generate personalized email opener
    """

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'
        })

    def enrich_lead(self, lead) -> Dict:
        """
        Full enrichment pipeline for a lead.

        Args:
            lead: Lead model instance with email, company, website

        Returns:
            Dict with enrichment data
        """
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
            # Step 1: Scrape company website
            website_content = None
            if lead.website:
                website_content = self._scrape_website(lead.website)
                enrichment["raw_data"]["website_content"] = website_content[:2000] if website_content else None

            # Step 2: Search for company info and news
            search_content = self._search_company(lead.company)
            enrichment["raw_data"]["search_content"] = search_content[:2000] if search_content else None

            # Step 3: Analyze with AI (Gemini)
            if OPENROUTER_API_KEY and (website_content or search_content):
                analysis = self._analyze_company(
                    company_name=lead.company,
                    website_content=website_content,
                    search_content=search_content,
                    lead_name=lead.first_name or "there"
                )

                if analysis:
                    enrichment.update(analysis)
                    enrichment["success"] = True

            # Step 4: Generate personalized opener if we have data
            if enrichment["success"] and OPENROUTER_API_KEY:
                opener = self._generate_personalized_opener(
                    lead_name=lead.first_name or "there",
                    company_name=lead.company,
                    industry=enrichment.get("industry"),
                    company_description=enrichment.get("company_description"),
                    recent_news=enrichment.get("recent_news"),
                    pain_points=enrichment.get("pain_points")
                )
                enrichment["personalized_opener"] = opener

        except Exception as e:
            logger.error(f"Enrichment failed for {lead.email}: {str(e)}")
            enrichment["error"] = str(e)

        return enrichment

    def _scrape_website(self, url: str) -> Optional[str]:
        """Scrape website using Jina AI Reader (FREE)"""
        try:
            # Ensure URL has protocol
            if not url.startswith('http'):
                url = f"https://{url}"

            # Use Jina AI Reader
            jina_url = f"https://r.jina.ai/{url}"
            headers = {}
            if JINA_API_KEY:
                headers["Authorization"] = f"Bearer {JINA_API_KEY}"

            response = self.session.get(jina_url, headers=headers, timeout=30)

            if response.status_code == 200:
                content = response.text
                # Clean up and limit content
                content = re.sub(r'\s+', ' ', content)
                return content[:5000]  # Limit to 5000 chars

        except Exception as e:
            logger.debug(f"Website scrape failed for {url}: {str(e)}")

        return None

    def _search_company(self, company_name: str) -> Optional[str]:
        """Search for company info using Jina Search (FREE)"""
        try:
            query = f"{company_name} company about news"
            url = f"https://s.jina.ai/{requests.utils.quote(query)}"

            headers = {"Accept": "application/json"}
            if JINA_API_KEY:
                headers["Authorization"] = f"Bearer {JINA_API_KEY}"

            response = self.session.get(url, headers=headers, timeout=30)

            if response.status_code == 200:
                return response.text[:5000]

        except Exception as e:
            logger.debug(f"Company search failed: {str(e)}")

        return None

    def _call_ai(self, prompt: str) -> Optional[str]:
        """Call OpenRouter API (FREE Llama 3.1 405B) and return the response text"""
        if not OPENROUTER_API_KEY:
            logger.warning("OpenRouter API key not configured")
            return None

        try:
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                "HTTP-Referer": "https://ratetapmx.com",
                "X-Title": "RateTapMX Lead Enrichment"
            }

            payload = {
                "model": OPENROUTER_MODEL,
                "messages": [
                    {"role": "user", "content": prompt}
                ],
                "temperature": 0.7,
                "max_tokens": 1000
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

    def _analyze_company(self, company_name: str, website_content: str,
                         search_content: str, lead_name: str) -> Optional[Dict]:
        """Use Gemini to analyze and extract structured company data"""
        combined_content = ""
        if website_content:
            combined_content += f"WEBSITE CONTENT:\n{website_content}\n\n"
        if search_content:
            combined_content += f"SEARCH RESULTS:\n{search_content}\n\n"

        if not combined_content.strip():
            return None

        prompt = f"""Analyze this information about "{company_name}" and extract structured data.

{combined_content}

Based on this information, provide a JSON response with:
1. "industry": The restaurant type in Spanish (e.g., "Taquería", "Restaurante", "Cafetería", "Mariscos", "Comida Corrida", "Bar")
2. "company_size": Estimated size ("1-10", "11-50", "51-200", "201-500", "500+") - guess based on context
3. "company_description": 1-2 sentence description in Spanish of what the restaurant does
4. "recent_news": Any recent news, achievements, expansions, new locations, awards (null if none found) - in Spanish if found
5. "pain_points": 2-3 pain points in Spanish that our review management software could help with (getting more Google reviews, responding to bad reviews, improving star ratings)

Return ONLY valid JSON, no other text:
{{"industry": "...", "company_size": "...", "company_description": "...", "recent_news": "...", "pain_points": "..."}}
"""

        try:
            result = self._call_ai(prompt)
            if result:
                # Extract JSON from response
                json_match = re.search(r'\{[\s\S]*\}', result)
                if json_match:
                    return json.loads(json_match.group())

        except Exception as e:
            logger.error(f"AI analysis failed: {str(e)}")

        return None

    def _generate_personalized_opener(self, lead_name: str, company_name: str,
                                       industry: str, company_description: str,
                                       recent_news: str, pain_points: str) -> Optional[str]:
        """Generate a personalized email opening line using Gemini"""
        prompt = f"""Escribe una línea de apertura corta y casual (1 oración) EN ESPAÑOL para un correo frío a un dueño de restaurante pequeño en León, México.

Info del restaurante:
- Nombre: {company_name}
- Tipo: {industry or 'Restaurante'}
- Sobre ellos: {company_description or 'Desconocido'}
- Noticias recientes: {recent_news or 'Ninguna'}

Reglas:
1. Suena como una persona real, NO como vendedor
2. Si hay noticias (nueva sucursal, premio), menciónalo casual tipo "vi que abrieron nueva sucursal - ¡qué bien!"
3. Si no hay noticias, comenta algo específico de ellos (su comida, ambiente, etc.)
4. Súper corto - una oración casual
5. NADA corporativo, NADA de "espero que estés bien", NADA de "me gustaría contactarte"
6. Escribe como alguien local que conoce la escena de restaurantes en León

Buenos ejemplos:
- "Vi que acaban de llegar a 500 reseñas en Google - ¡eso está increíble!"
- "Las fotos de sus tacos al pastor en Google se ven buenísimas."
- "He escuchado puras cosas buenas de {company_name} últimamente."

Malos ejemplos (muy formales/vendedor):
- "Me encontré con su restaurante y me impresionó..."
- "Noté que su establecimiento ha estado..."
- "Quería contactarlo respecto a..."

Responde SOLO la oración de apertura en español. Sin comillas."""

        try:
            opener = self._call_ai(prompt)
            if opener:
                # Clean up any quotes and extra whitespace
                opener = opener.strip().strip('"\'').strip()
                # Remove any "Here's..." prefix Gemini might add
                opener = re.sub(r'^(Here\'s|Here is)[^:]*:\s*', '', opener, flags=re.IGNORECASE)
                return opener

        except Exception as e:
            logger.error(f"Opener generation failed: {str(e)}")

        return None


def enrich_lead_in_db(app, db, lead_id: int) -> bool:
    """
    Enrich a lead and save to database.

    Args:
        app: Flask app instance
        db: SQLAlchemy db instance
        lead_id: ID of lead to enrich

    Returns:
        True if successful
    """
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
            # Convert pain_points to string if it's a list
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
        else:
            logger.warning(f"Lead {lead_id} enrichment returned no data")
            return False


def enrich_all_unenriched_leads(app, db, limit: int = 10) -> Dict:
    """
    Enrich all leads that haven't been enriched yet.

    Args:
        app: Flask app instance
        db: SQLAlchemy db instance
        limit: Max leads to enrich in one batch

    Returns:
        Dict with results summary
    """
    from models import Lead

    results = {
        "processed": 0,
        "enriched": 0,
        "failed": 0,
        "skipped": 0
    }

    with app.app_context():
        # Get unenriched leads with company info
        leads = Lead.query.filter(
            Lead.enriched == False,
            Lead.company.isnot(None),
            Lead.company != ''
        ).limit(limit).all()

        for lead in leads:
            results["processed"] += 1

            if enrich_lead_in_db(app, db, lead.id):
                results["enriched"] += 1
            else:
                results["failed"] += 1

    logger.info(f"Enrichment batch complete: {results}")
    return results
