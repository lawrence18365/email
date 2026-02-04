#!/usr/bin/env python3
"""
Test the FREE lead finder with Jina AI

Usage:
    python test_lead_finder.py
"""

import os
from dotenv import load_dotenv

load_dotenv()

# Quick test of Jina API
def test_jina():
    import requests

    JINA_API_KEY = os.getenv('JINA_API_KEY')

    if not JINA_API_KEY:
        print("ERROR: JINA_API_KEY not set in .env file")
        print("\nAdd this to your .env file:")
        print("JINA_API_KEY=jina_e8fd3e096ef94434864cc32204dceaa39YYzUkkoE_LSZBcIUi8_-dqYvv-r")
        return False

    print(f"Using Jina API key: {JINA_API_KEY[:20]}...")

    # Test 1: Search
    print("\n1. Testing Jina Search (s.jina.ai)...")
    try:
        response = requests.get(
            "https://s.jina.ai/?q=mortgage+broker+Mexico+email",
            headers={"Authorization": f"Bearer {JINA_API_KEY}"},
            timeout=30
        )
        print(f"   Status: {response.status_code}")
        if response.status_code == 200:
            print(f"   Response length: {len(response.text)} chars")
            print("   Search working!")
        else:
            print(f"   Error: {response.text[:200]}")
    except Exception as e:
        print(f"   Error: {str(e)}")

    # Test 2: Read
    print("\n2. Testing Jina Reader (r.jina.ai)...")
    try:
        response = requests.get(
            "https://r.jina.ai/https://example.com",
            headers={"Authorization": f"Bearer {JINA_API_KEY}"},
            timeout=30
        )
        print(f"   Status: {response.status_code}")
        if response.status_code == 200:
            print(f"   Response length: {len(response.text)} chars")
            print("   Reader working!")
        else:
            print(f"   Error: {response.text[:200]}")
    except Exception as e:
        print(f"   Error: {str(e)}")

    return True


def test_lead_finder():
    """Test the full lead finder"""
    from lead_finder import FreeLeadFinder

    print("\n3. Testing FreeLeadFinder...")
    finder = FreeLeadFinder()

    # Test with simple criteria
    criteria = {
        "industry": "mortgage",
        "location": "Mexico",
        "keywords": ["broker", "lending"],
        "job_titles": ["CEO", "director"]
    }

    print(f"   Searching for leads with criteria: {criteria}")
    leads = finder.find_leads(criteria, limit=5)

    print(f"\n   Found {len(leads)} leads:")
    for lead in leads:
        print(f"   - {lead.get('email')} ({lead.get('company', 'Unknown')})")

    return leads


if __name__ == "__main__":
    print("="*60)
    print("Testing FREE Lead Finder with Jina AI")
    print("="*60)

    if test_jina():
        print("\nJina API working! Testing lead finder...")
        leads = test_lead_finder()

        print("\n" + "="*60)
        print("TEST COMPLETE")
        print("="*60)

        if leads:
            print(f"SUCCESS: Found {len(leads)} leads for free!")
        else:
            print("No leads found - try different search criteria")
    else:
        print("\nFix the Jina API key first, then re-run this test.")
