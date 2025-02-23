import logging
import json  # Add at the top of both files
from typing import Dict, Optional, List, Any
from ai_services_api.services.data.openalex.database_manager import DatabaseManager
from ai_services_api.services.data.openalex.ai_summarizer import TextSummarizer
from ai_services_api.services.data.openalex.text_processor import (
    safe_str, 
    convert_inverted_index_to_text, 
    truncate_text
)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s: %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

class PublicationProcessor:
    def __init__(self, db: DatabaseManager, summarizer: TextSummarizer):
        """Initialize PublicationProcessor."""
        self.db = db
        self.summarizer = summarizer
        self._setup_database_indexes()
    def _setup_database_indexes(self) -> None:
        """Create necessary database indexes and tables if they don't exist."""
        try:
            # First create tables
            tables = [
                """
                CREATE TABLE IF NOT EXISTS publication_tags (
                    doi VARCHAR(255),
                    title TEXT,
                    tag_id INTEGER,
                    PRIMARY KEY (doi, tag_id)
                )
                """
            ]
            
            for table_sql in tables:
                try:
                    self.db.execute(table_sql)
                except Exception as e:
                    logger.error(f"Error creating table: {e}")
                    raise

            # Then create indexes
            indexes = [
                """
                CREATE INDEX IF NOT EXISTS idx_resources_doi 
                ON resources_resource(doi);
                """,
                """
                CREATE INDEX IF NOT EXISTS idx_authors_name 
                ON authors_ai(name);
                """,
                """
                CREATE INDEX IF NOT EXISTS idx_author_publication 
                ON author_publication_ai(doi, author_id);
                """,
                """
                CREATE INDEX IF NOT EXISTS idx_publication_tags 
                ON publication_tags(doi, tag_id);
                """
            ]
            
            for index_sql in indexes:
                self.db.execute(index_sql)
                
            logger.info("Database tables and indexes verified/created successfully")
        except Exception as e:
            logger.error(f"Error setting up database indexes: {e}")

    def _doi_exists(self, doi: str) -> bool:
        """
        Check if a DOI already exists in the database.
        
        Args:
            doi: Digital Object Identifier to check
            
        Returns:
            bool: True if DOI exists, False otherwise
        """
        try:
            result = self.db.execute("""
                SELECT EXISTS (
                    SELECT 1 
                    FROM resources_resource 
                    WHERE doi = %s
                )
            """, (doi,))
            return result[0][0] if result else False
        except Exception as e:
            logger.error(f"Error checking DOI existence: {e}")
            return False

    def _check_publication_exists(self, title: str, doi: Optional[str] = None) -> tuple[bool, Optional[str]]:
        """
        Check if publication exists and get its summary.
        
        Args:
            title: Publication title
            doi: Optional DOI
            
        Returns:
            tuple: (exists, summary)
        """
        try:
            if doi:
                result = self.db.execute("""
                    SELECT EXISTS(SELECT 1 FROM resources_resource WHERE doi = %s),
                           (SELECT summary FROM resources_resource WHERE doi = %s)
                    """, (doi, doi))
                if result and result[0][0]:
                    return True, result[0][1]

            # If no DOI or DOI not found, check by title
            result = self.db.execute("""
                SELECT EXISTS(SELECT 1 FROM resources_resource WHERE title = %s),
                       (SELECT summary FROM resources_resource WHERE title = %s)
                """, (title, title))
            if result:
                return result[0][0], result[0][1]
            return False, None
        except Exception as e:
            logger.error(f"Error checking publication existence: {e}")
            return False, None

    def _clean_and_validate_work(self, work: Dict) -> tuple[Optional[str], Optional[str]]:
        """Clean and validate work data."""
        try:
            doi = safe_str(work.get('doi'))
            title = safe_str(work.get('title'))
            
            if not title:
                logger.warning("Invalid title")
                return None, None

            # DOI can be None, but title must exist
            return doi if doi and doi != "N/A" else None, title
            
        except Exception as e:
            logger.error(f"Error in work validation: {e}")
            return None, None

    def process_single_work(self, work: Dict, source: str = 'openalex') -> bool:
        """Process a single publication work."""
        try:
            # Clean and validate work
            doi, title = self._clean_and_validate_work(work)
            if not title:  # Title is required, DOI is optional
                return False

            # Check if publication exists and has summary
            exists, existing_summary = self._check_publication_exists(title, doi)
            if exists and existing_summary:
                logger.info(f"Publication already exists with summary. Skipping.")
                return False

            # Process abstract
            abstract = work.get('abstract', '')
            if not abstract:
                logger.info("No abstract available, generating description from title")
                abstract = f"Publication about {title}"

            # Generate summary if needed
            summary = existing_summary
            if not summary:
                try:
                    logger.info(f"Generating summary for: {title}")
                    summary = self.summarizer.summarize(title, abstract)
                except Exception as e:
                    logger.error(f"Error generating summary: {e}")
                    summary = abstract[:500]

            # Extract metadata
            metadata = self._extract_metadata(work)

            try:
                self.db.execute("BEGIN")
                
                # Add main publication record
                self.db.add_publication(
                    title=title,
                    abstract=abstract,
                    summary=summary,
                    source=source,
                    doi=doi,
                    **metadata
                )

                # Process authors as tags if from website
                if source == 'website' and work.get('tags'):
                    for tag_info in work['tags']:
                        try:
                            tag_id = self.db.add_tag(tag_info)
                            identifier = doi if doi else title
                            self.db.link_publication_tag(identifier, tag_id)
                        except Exception as e:
                            logger.error(f"Error processing website tag {tag_info.get('name')}: {e}")
                            continue

                # Process authors for non-website sources
                elif work.get('authorships'):
                    for authorship in work.get('authorships', []):
                        try:
                            author = authorship.get('author', {})
                            if not author:
                                continue

                            author_name = author.get('display_name')
                            if not author_name:
                                continue

                            tag_info = {
                                'name': author_name,
                                'tag_type': 'author',
                                'additional_metadata': json.dumps({
                                    'orcid': author.get('orcid'),
                                    'institutions': [
                                        aff.get('display_name') 
                                        for aff in authorship.get('institutions', [])
                                    ],
                                    'is_corresponding': authorship.get('is_corresponding', False)
                                })
                            }
                            tag_id = self.db.add_tag(tag_info)
                            if doi:
                                self.db.link_publication_tag(doi, tag_id)
                            else:
                                self.db.link_publication_tag(title, tag_id)

                        except Exception as e:
                            logger.error(f"Error processing author tag: {e}")

                    # Process concepts/topics as domain tags
                    for concept in work.get('concepts', []):
                        try:
                            if not concept.get('display_name'):
                                continue

                            tag_info = {
                                'name': concept['display_name'],
                                'tag_type': 'domain',
                                'additional_metadata': json.dumps({
                                    'score': concept.get('score'),
                                    'level': concept.get('level'),
                                    'wikidata_id': concept.get('wikidata'),
                                    'source': source
                                })
                            }
                            tag_id = self.db.add_tag(tag_info)
                            if doi:
                                self.db.link_publication_tag(doi, tag_id)
                            else:
                                self.db.link_publication_tag(title, tag_id)

                        except Exception as e:
                            logger.error(f"Error processing concept tag: {e}")

                # Add type tag if available
                if metadata.get('type'):
                    try:
                        type_tag_info = {
                            'name': metadata['type'],
                            'tag_type': 'publication_type',
                            'additional_metadata': json.dumps({
                                'source': source
                            })
                        }
                        tag_id = self.db.add_tag(type_tag_info)
                        identifier = doi if doi else title
                        self.db.link_publication_tag(identifier, tag_id)
                    except Exception as e:
                        logger.error(f"Error processing type tag: {e}")

                self.db.execute("COMMIT")
                logger.info(f"Successfully processed publication: {title}")
                return True

            except Exception as e:
                self.db.execute("ROLLBACK")
                logger.error(f"Error in database transaction: {e}")
                return False

        except Exception as e:
            logger.error(f"Error processing work: {e}")
            return False
    def _extract_metadata(self, work: Dict) -> Dict[str, Any]:
        """
        Extract additional metadata from work.
        
        Args:
            work: Publication work dictionary
            
        Returns:
            dict: Extracted metadata
        """
        try:
            return {
                'type': safe_str(work.get('type')),
                'publication_year': work.get('publication_year'),
                'citation_count': work.get('cited_by_count'),
                'language': safe_str(work.get('language')),
                'publisher': safe_str(work.get('publisher')),
                'journal': safe_str(work.get('host_venue', {}).get('display_name')),
                'fields_of_study': work.get('fields_of_study', [])
            }
        except Exception as e:
            logger.error(f"Error extracting metadata: {e}")
            return {}

    def _process_authors(self, authorships: List[Dict], doi: str) -> None:
        """
        Process all authors from a work and add them as author tags.
        
        Args:
            authorships: List of authorship information
            doi: Publication DOI
        """
        try:
            for authorship in authorships:
                author = authorship.get('author', {})
                if not author:
                    continue

                author_name = author.get('display_name')
                if not author_name:
                    continue

                tag_info = {
                    'name': author_name,
                    'type': 'author',
                    'metadata': {
                        'orcid': author.get('orcid'),
                        'openalex_id': author.get('id'),
                        'affiliations': [
                            aff.get('display_name') 
                            for aff in authorship.get('institutions', [])
                        ],
                        'is_corresponding': authorship.get('is_corresponding', False)
                    }
                }

                try:
                    tag_id = self.db.add_tag(tag_info)
                    self.db.link_publication_tag(doi, tag_id)
                    logger.debug(f"Processed author tag: {author_name}")
                except Exception as e:
                    logger.error(f"Error adding author tag: {e}")

        except Exception as e:
            logger.error(f"Error processing authors: {e}")

    def _process_domains(self, work: Dict, doi: str) -> None:
        """
        Process domain information from work and add as domain tags.
        
        Args:
            work: Work dictionary with domain information
            doi: Publication DOI
        """
        try:
            # Process topics/domains
            for topic in work.get('topics', []):
                # Process domain
                domain = topic.get('domain', {}).get('display_name')
                if domain:
                    tag_info = {
                        'name': domain,
                        'type': 'domain',
                        'metadata': {
                            'score': topic.get('score'),
                            'level': topic.get('level'),
                            'field': topic.get('field', {}).get('display_name'),
                            'subfields': [
                                sf.get('display_name') 
                                for sf in topic.get('subfields', [])
                            ]
                        }
                    }
                    try:
                        tag_id = self.db.add_tag(tag_info)
                        self.db.link_publication_tag(doi, tag_id)
                        logger.debug(f"Processed domain tag: {domain}")
                    except Exception as e:
                        logger.error(f"Error adding domain tag: {e}")

        except Exception as e:
            logger.error(f"Error processing domains: {e}")

    def _process_tag(self, concept: Dict, doi: str) -> None:
        """
        Process a single concept/tag and link to publication.
        
        Args:
            concept: Concept information dictionary
            doi: Publication DOI
        """
        try:
            tag_name = concept.get('display_name')
            if not tag_name:
                return

            tag_info = {
                'name': tag_name,
                'type': 'concept',
                'score': concept.get('score'),
                'level': concept.get('level'),
                'wikidata_id': concept.get('wikidata')
            }

            try:
                tag_id = self.db.add_tag(tag_info)
                self.db.link_publication_tag(doi, tag_id)
                logger.debug(f"Processed tag: {tag_name} for publication {doi}")
            except Exception as e:
                logger.error(f"Error adding tag to database: {e}")

        except Exception as e:
            logger.error(f"Error processing tag for publication {doi}: {e}")

    def process_batch(self, works: List[Dict], source: str = 'openalex') -> int:
        """
        Process a batch of works.
        
        Args:
            works: List of publication work dictionaries
            source: Source of the publications (default: 'openalex')
            
        Returns:
            int: Number of successfully processed works
        """
        successful = 0
        for work in works:
            try:
                if self.process_single_work(work, source):
                    successful += 1
            except Exception as e:
                logger.error(f"Error processing work in batch: {e}")
                continue
        return successful

    def close(self) -> None:
        """Clean up resources."""
        try:
            if hasattr(self, 'db'):
                self.db.close()
            logger.info("PublicationProcessor resources cleaned up")
        except Exception as e:
            logger.error(f"Error closing resources: {e}")

    def __enter__(self):
        """Context manager entry."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.close()
