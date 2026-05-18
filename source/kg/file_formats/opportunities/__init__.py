from __future__ import annotations

from source.kg.file_formats.opportunities.terraform_domain import TerraformDomainOpportunityDetector

FILE_FORMAT_OPPORTUNITY_DETECTORS = (TerraformDomainOpportunityDetector(),)

__all__ = ["FILE_FORMAT_OPPORTUNITY_DETECTORS", "TerraformDomainOpportunityDetector"]
