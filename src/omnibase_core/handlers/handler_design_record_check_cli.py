# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""File and CLI boundary for the design-record check (OMN-21509)."""

from __future__ import annotations

import sys
from pathlib import Path

from omnibase_core.handlers.handler_design_record_check import HandlerDesignRecordCheck
from omnibase_core.models.common.model_validation_issue import ModelValidationIssue
from omnibase_core.models.contracts.subcontracts.model_validator_subcontract import (
    ModelValidatorSubcontract,
)
from omnibase_core.models.design_record.model_design_record_check_input import (
    ModelDesignRecordCheckInput,
)
from omnibase_core.models.design_record.model_design_record_check_result import (
    ModelDesignRecordCheckResult,
)
from omnibase_core.validation import validator_base
from omnibase_core.validation.validator_base import ValidatorBase


class ValidatorDesignRecord(ValidatorBase):
    """Validate design-record files using the shared pure handler."""

    validator_id = "design_record"

    def _get_contract_path(self) -> Path:
        """Find the committed contract alongside the base validator's contracts."""
        return (
            Path(validator_base.__file__).parent
            / "contracts"
            / "design_record.validation.yaml"
        )

    def _validate_file(
        self, path: Path, contract: ModelValidatorSubcontract
    ) -> tuple[ModelValidationIssue, ...]:
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return ()
        result = check_design_record_text(text, contract)
        return tuple(
            issue.model_copy(update={"file_path": path}) for issue in result.issues
        )


def load_design_record_contract() -> ModelValidatorSubcontract:
    """Load the committed design-record validation subcontract."""
    return ValidatorDesignRecord().contract


def check_design_record_text(
    text: str, contract: ModelValidatorSubcontract | None = None
) -> ModelDesignRecordCheckResult:
    """Check text using the supplied contract or the committed default."""
    return HandlerDesignRecordCheck().handle(
        ModelDesignRecordCheckInput(
            text=text,
            contract=load_design_record_contract() if contract is None else contract,
        )
    )


def main() -> int:
    """Run the design-record validator CLI."""
    return ValidatorDesignRecord.main()


if __name__ == "__main__":
    sys.exit(main())
