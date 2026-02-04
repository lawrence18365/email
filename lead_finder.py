"""
AI Lead Finder - FREE/Low-Cost Lead Prospecting

Finds leads using FREE tools:
- Jina AI Reader (r.jina.ai) - FREE web scraping
- Brave Search API - FREE 2,000 searches/month
- Serper.dev - FREE 2,500 searches/month
- Direct website scraping + regex email extraction
- Apify ($5/month) - optional for heavy scraping

NO expensive APIs needed (Apollo, Hunter, Clearbit)!
"""

import os
import re
import json
import logging
import requests
from datetime import datetime
from typing import List, Dict, Optional, Set
from urllib.parse import urlparse, quote_plus, urljoin
from anthropic import Anthropic
from dotenv import load_dotenv
import time

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize AI
anthropic = Anthropic(api_key=os.getenv('ANTHROPIC_API_KEY'))

# FREE API Keys (generous free tiers)
BRAVE_API_KEY = os.getenv('BRAVE_API_KEY')  # 2,000 free/month
SERPER_API_KEY = os.getenv('SERPER_API_KEY')  # 2,500 free/month
JINA_API_KEY = os.getenv('JINA_API_KEY')  # 10M free tokens
APIFY_API_KEY = os.getenv('APIFY_API_KEY')  # $5/month credits

# Google Places API (for restaurant/business discovery)
# Text Search Pro: 5,000 free/month, then $32/1000 (~$0.032/call)
# Place Details Essentials: 10,000 free/month, then $5/1000 (~$0.005/call)
GOOGLE_PLACES_API_KEY = os.getenv('GOOGLE_PLACES_API_KEY')

# Email regex pattern
EMAIL_PATTERN = re.compile(
    r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}',
    re.IGNORECASE
)

# Patterns to exclude (not real emails)
EXCLUDE_PATTERNS = [
    r'.*@example\.com',
    r'.*@test\.com',
    r'.*@localhost',
    r'.*@.*\.png',
    r'.*@.*\.jpg',
    r'.*@.*\.gif',
    r'.*@2x\.',
    r'.*@3x\.',
    r'noreply@',
    r'no-reply@',
    r'support@',
    r'info@',
    r'admin@',
    r'webmaster@',
    r'postmaster@',
]


class FreeLeadFinder:
    """Lead finder using FREE tools only"""

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'
        })
        self.found_emails: Set[str] = set()

    # =========================================================================
    # Main Search Methods
    # =========================================================================

    def find_leads(self, criteria: Dict, limit: int = 50) -> List[Dict]:
        """
        Find leads using FREE methods

        Args:
            criteria: {
                "industry": "fintech, mortgage",
                "location": "Mexico",
                "keywords": ["mortgage broker", "lending"],
                "job_titles": ["CEO", "founder"]
            }
            limit: Max leads to find

        Returns:
            List of lead dicts
        """
        leads = []
        self.found_emails = set()

        # Build search queries
        queries = self._build_search_queries(criteria)

        for query in queries[:5]:  # Limit queries to conserve free tier
            logger.info(f"Searching: {query}")

            # Try Jina Search first (10M free tokens!)
            if JINA_API_KEY:
                urls = self._jina_search(query, num_results=10)
            # Fallback to Brave Search (2,000 free/month)
            elif BRAVE_API_KEY:
                urls = self._brave_search(query, num_results=10)
            # Fallback to Serper (2,500 free/month)
            elif SERPER_API_KEY:
                urls = self._serper_search(query, num_results=10)
            # Fallback to DuckDuckGo (completely free, no API)
            else:
                urls = self._duckduckgo_search(query, num_results=10)

            # Scrape each URL for emails
            for url in urls:
                if len(leads) >= limit:
                    break

                page_leads = self._scrape_page_for_leads(url, criteria)
                leads.extend(page_leads)

            if len(leads) >= limit:
                break

            # Rate limiting
            time.sleep(1)

        # Deduplicate
        unique_leads = self._deduplicate_leads(leads)

        logger.info(f"Found {len(unique_leads)} unique leads")
        return unique_leads[:limit]

    def find_company_emails(self, company_name: str, domain: str) -> List[Dict]:
        """
        Find emails for a specific company

        Args:
            company_name: "Acme Corp"
            domain: "acmecorp.com"

        Returns:
            List of leads found
        """
        leads = []

        # Search for company contact page
        queries = [
            f'site:{domain} email contact',
            f'site:{domain} "contact us"',
            f'"{company_name}" email contact',
            f'"{company_name}" CEO founder email',
        ]

        for query in queries:
            if JINA_API_KEY:
                urls = self._jina_search(query, num_results=5)
            elif BRAVE_API_KEY:
                urls = self._brave_search(query, num_results=5)
            elif SERPER_API_KEY:
                urls = self._serper_search(query, num_results=5)
            else:
                urls = self._duckduckgo_search(query, num_results=5)

            for url in urls:
                page_leads = self._scrape_page_for_leads(url, {"company": company_name})
                leads.extend(page_leads)

            time.sleep(0.5)

        return self._deduplicate_leads(leads)

    # =========================================================================
    # Search APIs (FREE Tiers)
    # =========================================================================

    def _jina_search(self, query: str, num_results: int = 10) -> List[str]:
        """
        Search using Jina AI Search API

        FREE: 10M tokens with API key
        Endpoint: https://s.jina.ai/?q=query
        """
        try:
            url = f"https://s.jina.ai/?q={quote_plus(query)}"
            headers = {
                "Accept": "application/json"
            }
            if JINA_API_KEY:
                headers["Authorization"] = f"Bearer {JINA_API_KEY}"

            response = self.session.get(url, headers=headers, timeout=30)

            if response.status_code == 200:
                # Jina returns markdown with URLs
                content = response.text
                # Extract URLs from the response
                urls = re.findall(r'https?://[^\s\)\]\"\'<>]+', content)
                # Filter and deduplicate
                seen = set()
                unique_urls = []
                for u in urls:
                    # Clean URL
                    u = u.rstrip('.,;:')
                    if u not in seen and 'jina.ai' not in u:
                        seen.add(u)
                        unique_urls.append(u)
                return unique_urls[:num_results]

        except Exception as e:
            logger.error(f"Jina search error: {str(e)}")

        return []

    def _brave_search(self, query: str, num_results: int = 10) -> List[str]:
        """
        Search using Brave Search API

        FREE: 2,000 searches/month
        """
        if not BRAVE_API_KEY:
            return []

        try:
            url = "https://api.search.brave.com/res/v1/web/search"
            headers = {
                "Accept": "application/json",
                "X-Subscription-Token": BRAVE_API_KEY
            }
            params = {
                "q": query,
                "count": num_results
            }

            response = self.session.get(url, headers=headers, params=params, timeout=15)

            if response.status_code == 200:
                data = response.json()
                urls = []
                for result in data.get('web', {}).get('results', []):
                    urls.append(result.get('url'))
                return urls

        except Exception as e:
            logger.error(f"Brave search error: {str(e)}")

        return []

    def _serper_search(self, query: str, num_results: int = 10) -> List[str]:
        """
        Search using Serper.dev API

        FREE: 2,500 searches/month
        """
        if not SERPER_API_KEY:
            return []

        try:
            url = "https://google.serper.dev/search"
            headers = {
                "X-API-KEY": SERPER_API_KEY,
                "Content-Type": "application/json"
            }
            payload = {
                "q": query,
                "num": num_results
            }

            response = self.session.post(url, headers=headers, json=payload, timeout=15)

            if response.status_code == 200:
                data = response.json()
                urls = []
                for result in data.get('organic', []):
                    urls.append(result.get('link'))
                return urls

        except Exception as e:
            logger.error(f"Serper search error: {str(e)}")

        return []

    def _duckduckgo_search(self, query: str, num_results: int = 10) -> List[str]:
        """
        Search using DuckDuckGo (completely FREE, no API key needed)

        Uses the HTML version to avoid rate limits
        """
        try:
            # Use DuckDuckGo HTML search
            url = f"https://html.duckduckgo.com/html/?q={quote_plus(query)}"

            response = self.session.get(url, timeout=15)

            if response.status_code == 200:
                # Extract URLs from results
                urls = re.findall(r'href="(https?://[^"]+)"', response.text)
                # Filter out DuckDuckGo internal links
                urls = [u for u in urls if 'duckduckgo.com' not in u]
                return urls[:num_results]

        except Exception as e:
            logger.error(f"DuckDuckGo search error: {str(e)}")

        return []

    # =========================================================================
    # Google Places API (Restaurant/Business Discovery)
    # =========================================================================

    def google_places_search(self, query: str, location: str = None,
                             radius: int = 50000, place_type: str = None,
                             limit: int = 20) -> List[Dict]:
        """
        Search for businesses using Google Places Text Search API

        Tries New API first, falls back to Legacy API if not enabled.

        Pricing: 5,000 free/month, then $32/1000 calls (~$0.032/call)

        Args:
            query: Search text (e.g., "restaurants in Mexico City")
            location: Optional "lat,lng" for location bias
            radius: Search radius in meters (max 50000)
            place_type: Optional type filter (restaurant, cafe, bar, etc.)
            limit: Max results to return

        Returns:
            List of place dicts with name, address, phone, website, etc.
        """
        if not GOOGLE_PLACES_API_KEY:
            logger.warning("Google Places API key not configured")
            return []

        # Try New API first
        places = self._google_places_search_new(query, location, radius, place_type, limit)

        # Fallback to Legacy API if New API fails
        if not places:
            logger.info("Trying Legacy Places API...")
            places = self._google_places_search_legacy(query, location, radius, place_type, limit)

        return places

    def _google_places_search_new(self, query: str, location: str = None,
                                   radius: int = 50000, place_type: str = None,
                                   limit: int = 20) -> List[Dict]:
        """New Places API (places.googleapis.com)"""
        places = []

        try:
            url = "https://places.googleapis.com/v1/places:searchText"

            headers = {
                "Content-Type": "application/json",
                "X-Goog-Api-Key": GOOGLE_PLACES_API_KEY,
                "X-Goog-FieldMask": "places.id,places.displayName,places.formattedAddress,places.nationalPhoneNumber,places.internationalPhoneNumber,places.websiteUri,places.googleMapsUri,places.businessStatus,places.types,places.primaryType,places.rating,places.userRatingCount,places.priceLevel"
            }

            payload = {
                "textQuery": query,
                "maxResultCount": min(limit, 20),
                "languageCode": "en"
            }

            if location:
                lat, lng = map(float, location.split(','))
                payload["locationBias"] = {
                    "circle": {
                        "center": {"latitude": lat, "longitude": lng},
                        "radius": float(radius)
                    }
                }

            if place_type:
                payload["includedType"] = place_type

            response = self.session.post(url, headers=headers, json=payload, timeout=30)

            if response.status_code == 200:
                data = response.json()

                for place in data.get('places', []):
                    place_info = {
                        "place_id": place.get('id', ''),
                        "name": place.get('displayName', {}).get('text', ''),
                        "address": place.get('formattedAddress', ''),
                        "phone": place.get('nationalPhoneNumber') or place.get('internationalPhoneNumber', ''),
                        "website": place.get('websiteUri', ''),
                        "maps_url": place.get('googleMapsUri', ''),
                        "status": place.get('businessStatus', ''),
                        "types": place.get('types', []),
                        "primary_type": place.get('primaryType', ''),
                        "rating": place.get('rating'),
                        "review_count": place.get('userRatingCount'),
                        "price_level": place.get('priceLevel'),
                    }
                    places.append(place_info)

                logger.info(f"Google Places (New) found {len(places)} results for: {query}")
            elif response.status_code == 403:
                logger.warning("Places API (New) not enabled - will try Legacy API")
            else:
                logger.error(f"Google Places API error: {response.status_code}")

        except Exception as e:
            logger.error(f"Google Places search error: {str(e)}")

        return places

    def _google_places_search_legacy(self, query: str, location: str = None,
                                      radius: int = 50000, place_type: str = None,
                                      limit: int = 20) -> List[Dict]:
        """
        Legacy Places API (maps.googleapis.com/maps/api/place)

        Uses the older Text Search endpoint
        """
        places = []

        try:
            url = "https://maps.googleapis.com/maps/api/place/textsearch/json"

            params = {
                "query": query,
                "key": GOOGLE_PLACES_API_KEY,
            }

            if location:
                params["location"] = location
                params["radius"] = radius

            if place_type:
                params["type"] = place_type

            response = self.session.get(url, params=params, timeout=30)

            if response.status_code == 200:
                data = response.json()

                if data.get('status') == 'OK':
                    for place in data.get('results', [])[:limit]:
                        # Get additional details for phone/website
                        details = self._google_place_details_legacy(place.get('place_id', ''))

                        place_info = {
                            "place_id": place.get('place_id', ''),
                            "name": place.get('name', ''),
                            "address": place.get('formatted_address', ''),
                            "phone": details.get('phone', ''),
                            "website": details.get('website', ''),
                            "maps_url": f"https://www.google.com/maps/place/?q=place_id:{place.get('place_id', '')}",
                            "status": place.get('business_status', ''),
                            "types": place.get('types', []),
                            "primary_type": place.get('types', [''])[0] if place.get('types') else '',
                            "rating": place.get('rating'),
                            "review_count": place.get('user_ratings_total'),
                            "price_level": place.get('price_level'),
                        }
                        places.append(place_info)

                    logger.info(f"Google Places (Legacy) found {len(places)} results for: {query}")
                elif data.get('status') == 'REQUEST_DENIED':
                    logger.error(f"Legacy Places API denied: {data.get('error_message', 'Unknown error')}")
                else:
                    logger.warning(f"Legacy Places API status: {data.get('status')}")
            else:
                logger.error(f"Legacy Places API HTTP error: {response.status_code}")

        except Exception as e:
            logger.error(f"Legacy Places search error: {str(e)}")

        return places

    def _google_place_details_legacy(self, place_id: str) -> Dict:
        """Get phone/website from Legacy Place Details API"""
        if not place_id:
            return {}

        try:
            url = "https://maps.googleapis.com/maps/api/place/details/json"
            params = {
                "place_id": place_id,
                "fields": "formatted_phone_number,international_phone_number,website",
                "key": GOOGLE_PLACES_API_KEY,
            }

            response = self.session.get(url, params=params, timeout=15)

            if response.status_code == 200:
                data = response.json()
                if data.get('status') == 'OK':
                    result = data.get('result', {})
                    return {
                        "phone": result.get('formatted_phone_number') or result.get('international_phone_number', ''),
                        "website": result.get('website', ''),
                    }

        except Exception as e:
            logger.debug(f"Place details error: {str(e)}")

        return {}

    def google_places_nearby(self, location: str, radius: int = 5000,
                             place_type: str = "restaurant",
                             limit: int = 20) -> List[Dict]:
        """
        Search for nearby businesses using Google Places Nearby Search API

        Pricing: 5,000 free/month, then $32/1000 calls

        Args:
            location: "lat,lng" format (required)
            radius: Search radius in meters
            place_type: Type of place (restaurant, cafe, bar, etc.)
            limit: Max results

        Returns:
            List of nearby places
        """
        if not GOOGLE_PLACES_API_KEY:
            logger.warning("Google Places API key not configured")
            return []

        places = []

        try:
            lat, lng = map(float, location.split(','))

            url = "https://places.googleapis.com/v1/places:searchNearby"

            headers = {
                "Content-Type": "application/json",
                "X-Goog-Api-Key": GOOGLE_PLACES_API_KEY,
                "X-Goog-FieldMask": "places.id,places.displayName,places.formattedAddress,places.nationalPhoneNumber,places.internationalPhoneNumber,places.websiteUri,places.googleMapsUri,places.businessStatus,places.types,places.primaryType,places.rating,places.userRatingCount"
            }

            payload = {
                "locationRestriction": {
                    "circle": {
                        "center": {"latitude": lat, "longitude": lng},
                        "radius": float(radius)
                    }
                },
                "includedTypes": [place_type],
                "maxResultCount": min(limit, 20),
                "languageCode": "en"
            }

            response = self.session.post(url, headers=headers, json=payload, timeout=30)

            if response.status_code == 200:
                data = response.json()

                for place in data.get('places', []):
                    place_info = {
                        "place_id": place.get('id', ''),
                        "name": place.get('displayName', {}).get('text', ''),
                        "address": place.get('formattedAddress', ''),
                        "phone": place.get('nationalPhoneNumber') or place.get('internationalPhoneNumber', ''),
                        "website": place.get('websiteUri', ''),
                        "maps_url": place.get('googleMapsUri', ''),
                        "status": place.get('businessStatus', ''),
                        "types": place.get('types', []),
                        "primary_type": place.get('primaryType', ''),
                        "rating": place.get('rating'),
                        "review_count": place.get('userRatingCount'),
                    }
                    places.append(place_info)

                logger.info(f"Google Places Nearby found {len(places)} {place_type}s")
            else:
                logger.error(f"Google Places Nearby API error: {response.status_code} - {response.text}")

        except Exception as e:
            logger.error(f"Google Places Nearby search error: {str(e)}")

        return places

    def google_place_details(self, place_id: str) -> Dict:
        """
        Get detailed info for a specific place

        Pricing: 10,000 free/month, then $5/1000 calls (~$0.005/call)

        Args:
            place_id: Google Places ID

        Returns:
            Dict with full place details including contact info
        """
        if not GOOGLE_PLACES_API_KEY:
            return {}

        try:
            url = f"https://places.googleapis.com/v1/places/{place_id}"

            headers = {
                "X-Goog-Api-Key": GOOGLE_PLACES_API_KEY,
                "X-Goog-FieldMask": "id,displayName,formattedAddress,nationalPhoneNumber,internationalPhoneNumber,websiteUri,googleMapsUri,businessStatus,types,primaryType,rating,userRatingCount,priceLevel,regularOpeningHours,editorialSummary"
            }

            response = self.session.get(url, headers=headers, timeout=15)

            if response.status_code == 200:
                place = response.json()
                return {
                    "place_id": place.get('id', ''),
                    "name": place.get('displayName', {}).get('text', ''),
                    "address": place.get('formattedAddress', ''),
                    "phone": place.get('nationalPhoneNumber') or place.get('internationalPhoneNumber', ''),
                    "website": place.get('websiteUri', ''),
                    "maps_url": place.get('googleMapsUri', ''),
                    "status": place.get('businessStatus', ''),
                    "types": place.get('types', []),
                    "primary_type": place.get('primaryType', ''),
                    "rating": place.get('rating'),
                    "review_count": place.get('userRatingCount'),
                    "price_level": place.get('priceLevel'),
                    "hours": place.get('regularOpeningHours', {}),
                    "description": place.get('editorialSummary', {}).get('text', ''),
                }

        except Exception as e:
            logger.error(f"Google Place Details error: {str(e)}")

        return {}

    def find_restaurants(self, location: str, cuisine: str = None,
                        radius: int = 10000, limit: int = 50) -> List[Dict]:
        """
        Find restaurants in an area, with optional cuisine filter

        This is the main method for restaurant lead finding.

        Args:
            location: City name or "lat,lng"
            cuisine: Optional cuisine type (mexican, italian, etc.)
            radius: Search radius in meters
            limit: Max results

        Returns:
            List of restaurant leads ready to be added to database
        """
        leads = []

        # Build search query
        if cuisine:
            query = f"{cuisine} restaurants in {location}"
        else:
            query = f"restaurants in {location}"

        # Get places from Google
        places = self.google_places_search(query, radius=radius, place_type="restaurant", limit=limit)

        for place in places:
            # Skip if no useful contact info
            if not place.get('website') and not place.get('phone'):
                continue

            # Try to extract email from website
            email = None
            website = place.get('website', '')

            if website:
                # Scrape website for email
                page_leads = self._scrape_page_for_leads(website, {"company": place.get('name', '')})
                if page_leads:
                    email = page_leads[0].get('email')

            lead = {
                "first_name": "",
                "last_name": "",
                "email": email or "",
                "company": place.get('name', ''),
                "phone": place.get('phone', ''),
                "website": website,
                "address": place.get('address', ''),
                "source": f"google_places:{place.get('place_id', '')}",
                "notes": f"Rating: {place.get('rating', 'N/A')} ({place.get('review_count', 0)} reviews). Type: {place.get('primary_type', 'restaurant')}",
                "maps_url": place.get('maps_url', ''),
            }
            leads.append(lead)

        logger.info(f"Found {len(leads)} restaurant leads in {location}")
        return leads

    # =========================================================================
    # Web Scraping (FREE with Jina)
    # =========================================================================

    def _scrape_page_for_leads(self, url: str, criteria: Dict) -> List[Dict]:
        """
        Scrape a page for email addresses using Jina AI Reader (FREE)

        Jina converts any URL to clean text - perfect for email extraction
        """
        leads = []

        try:
            # Use Jina AI Reader (FREE) - just prepend r.jina.ai/
            jina_url = f"https://r.jina.ai/{url}"

            headers = {}
            if JINA_API_KEY:
                headers["Authorization"] = f"Bearer {JINA_API_KEY}"

            response = self.session.get(jina_url, headers=headers, timeout=30)

            if response.status_code == 200:
                content = response.text

                # Extract emails using regex
                emails = self._extract_emails(content)

                # Also try to extract from original page directly
                try:
                    direct_response = self.session.get(url, timeout=15)
                    if direct_response.status_code == 200:
                        direct_emails = self._extract_emails(direct_response.text)
                        emails.update(direct_emails)
                except:
                    pass

                # Create lead records
                for email in emails:
                    if email.lower() not in self.found_emails:
                        self.found_emails.add(email.lower())

                        # Try to extract name from email
                        name_parts = self._guess_name_from_email(email)

                        # Extract domain for company
                        domain = email.split('@')[1] if '@' in email else ''

                        lead = {
                            "email": email,
                            "first_name": name_parts.get('first_name', ''),
                            "last_name": name_parts.get('last_name', ''),
                            "company": self._domain_to_company(domain),
                            "website": f"https://{domain}" if domain else url,
                            "source": f"web_scrape:{urlparse(url).netloc}",
                            "source_url": url
                        }
                        leads.append(lead)

        except Exception as e:
            logger.debug(f"Error scraping {url}: {str(e)}")

        return leads

    def _scrape_direct(self, url: str) -> str:
        """Direct HTTP request to get page content"""
        try:
            response = self.session.get(url, timeout=15)
            if response.status_code == 200:
                return response.text
        except:
            pass
        return ""

    # =========================================================================
    # Email Extraction
    # =========================================================================

    def _extract_emails(self, content: str) -> Set[str]:
        """Extract email addresses from text content"""
        emails = set()

        # Find all email-like patterns
        matches = EMAIL_PATTERN.findall(content)

        for email in matches:
            email = email.lower().strip()

            # Skip if matches exclude patterns
            if self._should_exclude_email(email):
                continue

            # Basic validation
            if self._is_valid_email(email):
                emails.add(email)

        return emails

    def _should_exclude_email(self, email: str) -> bool:
        """Check if email should be excluded"""
        for pattern in EXCLUDE_PATTERNS:
            if re.match(pattern, email, re.IGNORECASE):
                return True
        return False

    def _is_valid_email(self, email: str) -> bool:
        """Basic email validation"""
        if not email or '@' not in email:
            return False

        parts = email.split('@')
        if len(parts) != 2:
            return False

        local, domain = parts

        # Check domain has at least one dot
        if '.' not in domain:
            return False

        # Check TLD length
        tld = domain.split('.')[-1]
        if len(tld) < 2 or len(tld) > 10:
            return False

        return True

    def _extract_emails_from_mailto(self, html: str) -> Set[str]:
        """Extract emails from mailto: links"""
        emails = set()
        mailto_pattern = re.compile(r'mailto:([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})')
        matches = mailto_pattern.findall(html)
        for email in matches:
            if self._is_valid_email(email):
                emails.add(email.lower())
        return emails

    # =========================================================================
    # Helper Methods
    # =========================================================================

    def _build_search_queries(self, criteria: Dict) -> List[str]:
        """Build search queries from criteria"""
        queries = []

        industry = criteria.get('industry', 'business')
        location = criteria.get('location', '')
        keywords = criteria.get('keywords', [])
        job_titles = criteria.get('job_titles', ['CEO', 'founder', 'owner'])

        # Query patterns
        patterns = [
            f'{industry} {location} company email contact',
            f'{industry} {location} CEO founder email',
            f'{industry} {location} "contact us" email',
        ]

        for keyword in keywords[:3]:
            patterns.append(f'{keyword} {location} email contact')

        for title in job_titles[:2]:
            patterns.append(f'{industry} {location} {title} email')

        # Add site-specific searches for common business directories
        if location:
            patterns.append(f'{industry} {location} site:linkedin.com/company')
            patterns.append(f'{industry} {location} site:crunchbase.com')

        return patterns

    def _guess_name_from_email(self, email: str) -> Dict[str, str]:
        """Try to extract name from email address"""
        local_part = email.split('@')[0]

        # Common patterns: john.doe, johndoe, j.doe, john_doe
        result = {'first_name': '', 'last_name': ''}

        # Remove numbers
        clean = re.sub(r'\d+', '', local_part)

        if '.' in clean:
            parts = clean.split('.')
            if len(parts) >= 2:
                result['first_name'] = parts[0].capitalize()
                result['last_name'] = parts[-1].capitalize()
        elif '_' in clean:
            parts = clean.split('_')
            if len(parts) >= 2:
                result['first_name'] = parts[0].capitalize()
                result['last_name'] = parts[-1].capitalize()
        elif len(clean) > 3:
            # Might be firstname or firstlast
            result['first_name'] = clean.capitalize()

        return result

    def _domain_to_company(self, domain: str) -> str:
        """Convert domain to company name guess"""
        if not domain:
            return ''

        # Remove common TLDs and www
        name = domain.replace('www.', '')
        name = re.sub(r'\.(com|org|net|io|co|mx|us|uk).*$', '', name)

        # Capitalize
        name = name.replace('-', ' ').replace('_', ' ')
        return name.title()

    def _deduplicate_leads(self, leads: List[Dict]) -> List[Dict]:
        """Remove duplicate leads by email"""
        seen = set()
        unique = []

        for lead in leads:
            email = lead.get('email', '').lower()
            if email and email not in seen:
                seen.add(email)
                unique.append(lead)

        return unique

    # =========================================================================
    # AI-Enhanced Methods
    # =========================================================================

    def ai_find_companies(self, criteria: Dict, limit: int = 20) -> List[Dict]:
        """
        Use AI to suggest companies to target

        Returns list of companies with names and domains to search
        """
        prompt = f"""Find {limit} real companies that would be good prospects for RateTapMX (rate comparison/financial services).

Criteria:
- Industry: {criteria.get('industry', 'financial services, mortgage, real estate')}
- Location: {criteria.get('location', 'Mexico, Latin America')}
- Size: {criteria.get('company_size', 'small to medium')}
- Keywords: {', '.join(criteria.get('keywords', []))}

For each company provide:
1. Company name (real company)
2. Website domain
3. Why they'd be a good prospect

Return as JSON array:
[{{"name": "Company Name", "domain": "company.com", "reason": "..."}}]

Focus on REAL companies that actually exist.
"""

        try:
            response = anthropic.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=4096,
                messages=[{"role": "user", "content": prompt}]
            )

            result = response.content[0].text
            json_match = re.search(r'\[[\s\S]*\]', result)

            if json_match:
                return json.loads(json_match.group())

        except Exception as e:
            logger.error(f"AI company search error: {str(e)}")

        return []

    def ai_enrich_lead(self, lead: Dict) -> Dict:
        """Use AI to enrich lead information"""
        prompt = f"""Given this lead information, provide likely additional details:

Email: {lead.get('email')}
Company: {lead.get('company', 'Unknown')}
Website: {lead.get('website', '')}

Based on the email pattern and company, estimate:
1. First name (from email pattern)
2. Last name (from email pattern)
3. Likely job title
4. Industry

Return as JSON:
{{"first_name": "...", "last_name": "...", "title": "...", "industry": "..."}}
"""

        try:
            response = anthropic.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=500,
                messages=[{"role": "user", "content": prompt}]
            )

            result = response.content[0].text
            json_match = re.search(r'\{[\s\S]*\}', result)

            if json_match:
                enriched = json.loads(json_match.group())
                lead.update({k: v for k, v in enriched.items() if v and not lead.get(k)})

        except Exception as e:
            logger.debug(f"AI enrichment error: {str(e)}")

        return lead


class LeadFinderScheduler:
    """Scheduler for automatic lead finding"""

    def __init__(self, app, db):
        self.app = app
        self.db = db
        self.finder = FreeLeadFinder()

    def run_prospecting(self, criteria: Dict = None, limit: int = 20,
                        auto_add: bool = True) -> Dict:
        """
        Run lead prospecting and optionally add to database

        Args:
            criteria: Search criteria (uses defaults if None)
            limit: Maximum leads to find
            auto_add: Automatically add leads to database

        Returns:
            Dict with results summary
        """
        from models import Lead

        # Default criteria
        if criteria is None:
            criteria = {
                "industry": "financial services, mortgage, real estate, fintech",
                "location": "Mexico, Latin America",
                "company_size": "small to medium",
                "keywords": ["mortgage", "lending", "financial services", "rates", "loans"],
                "job_titles": ["CEO", "CFO", "Owner", "Director", "Manager"]
            }

        # Find leads
        leads = self.finder.find_leads(criteria, limit=limit)

        # Add to database if requested
        added = 0
        skipped = 0

        if auto_add:
            with self.app.app_context():
                for lead_data in leads:
                    email = lead_data.get('email', '').lower().strip()

                    if not email:
                        skipped += 1
                        continue

                    # Check if exists
                    existing = Lead.query.filter_by(email=email).first()
                    if existing:
                        skipped += 1
                        continue

                    # Add lead
                    lead = Lead(
                        email=email,
                        first_name=lead_data.get('first_name', ''),
                        last_name=lead_data.get('last_name', ''),
                        company=lead_data.get('company', ''),
                        website=lead_data.get('website', ''),
                        source=lead_data.get('source', 'ai_prospecting'),
                        status='new'
                    )
                    self.db.session.add(lead)
                    added += 1

                self.db.session.commit()

        result = {
            "found": len(leads),
            "added": added,
            "skipped": skipped,
            "leads": leads if not auto_add else None
        }

        logger.info(f"Prospecting complete: found {len(leads)}, added {added}, skipped {skipped}")
        return result
