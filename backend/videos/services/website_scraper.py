"""Sitemap URL discovery for doctor websites (no HTML scrape).

Implementation lives in app.services.topics.
"""

from app.services.topics import scrape_doctor_website

__all__ = ["scrape_doctor_website"]
