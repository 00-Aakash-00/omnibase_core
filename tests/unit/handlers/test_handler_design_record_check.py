# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Tests for the design-record check handler (OMN-21509, task T-P1b).

The verdict cases reproduce the ones the merged omnimarket check was tested with
(OMN-21460). The rule tables the merged check held as module constants live in
``validation/contracts/design_record.validation.yaml``; the fixture-contract
cases remove one entry and watch the verdict on the fixture that entry catches
change.
"""

from __future__ import annotations

import ast
import copy
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
import yaml

from omnibase_core.enums import EnumSeverity
from omnibase_core.errors.model_onex_error import ModelOnexError
from omnibase_core.handlers import handler_design_record_check as handler_module
from omnibase_core.handlers.handler_design_record_check import (
    HandlerDesignRecordCheck,
)
from omnibase_core.handlers.handler_design_record_check_cli import (
    ValidatorDesignRecord,
    check_design_record_text,
    load_design_record_contract,
)
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

pytestmark = pytest.mark.unit

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "design_record"
CONTRACT_PATH = (
    Path(validator_base.__file__).parent / "contracts" / "design_record.validation.yaml"
)

HEAD = """\
Intended state: the queue drains within one hour.
Live check command: onex run-node node_queue_probe
Live check failing reading: depth 40 before the build.
"""
HEADER = "| Failure mode | How | Detected by | Severity | Detector |\n| -- | -- | -- | -- | -- |\n"

RULE_IDS = {
    "record_missing",
    "intended_state_missing",
    "live_check_command_missing",
    "failure_mode_table_missing",
    "failure_mode_table_empty",
    "row_without_detector_or_gap",
    "severity_out_of_range",
}


def _check(
    text: str, contract: ModelValidatorSubcontract | None = None
) -> ModelDesignRecordCheckResult:
    return HandlerDesignRecordCheck().handle(
        ModelDesignRecordCheckInput(
            text=text, contract=contract or load_design_record_contract()
        )
    )


def _codes(result: ModelDesignRecordCheckResult) -> set[str | None]:
    return {issue.code for issue in result.issues}


def _contract_with(
    mutate: Callable[[dict[str, dict[str, Any]]], None],
) -> ModelValidatorSubcontract:
    """The committed contract with `mutate` applied to its rules, by rule id."""
    data = yaml.safe_load(CONTRACT_PATH.read_text("utf-8"))["validation"]
    rules = {rule["rule_id"]: copy.deepcopy(rule) for rule in data["rules"]}
    mutate(rules)
    data["rules"] = list(rules.values())
    return ModelValidatorSubcontract.model_validate(data)


def test_empty_failure_mode_table_is_refused_naming_the_part() -> None:
    result = _check(HEAD + HEADER)
    assert "failure_mode_table_empty" in _codes(result)
    assert any(
        (i.context or {}).get("part") == "failure-mode table" for i in result.issues
    )
    assert result.failure_mode_rows == 0


def test_missing_table_is_refused() -> None:
    assert "failure_mode_table_missing" in _codes(_check(HEAD))


def test_row_with_no_detector_and_no_gap_is_refused() -> None:
    result = _check(HEAD + HEADER + "| stalls | lock | none | 2 | |\n")
    assert _codes(result) == {"row_without_detector_or_gap"}
    assert result.rows_without_detector_or_gap == 1
    assert (result.issues[0].context or {}).get("row") == "1"


def test_row_with_gap_mark_or_detector_is_accepted() -> None:
    body = (
        HEAD
        + HEADER
        + "| stalls | lock | none | 2 | GAP |\n| dup | race | probe | 1 | test_x.py |\n"
    )
    result = _check(body)
    assert result.issues == ()
    assert result.failure_mode_rows == 2
    assert result.rows_without_detector_or_gap == 0


def test_no_live_check_command_is_refused() -> None:
    body = HEAD.replace("Live check command: onex run-node node_queue_probe\n", "")
    result = _check(body + HEADER + "| a | b | c | 1 | GAP |\n")
    assert _codes(result) == {"live_check_command_missing"}
    assert result.live_check_command_present is False


def test_no_intended_state_is_refused() -> None:
    body = HEAD.replace("Intended state: the queue drains within one hour.\n", "")
    result = _check(body + HEADER + "| a | b | c | 1 | GAP |\n")
    assert _codes(result) == {"intended_state_missing"}


def test_body_without_a_record_is_refused() -> None:
    result = _check("# A plan\n\nNothing here.\n")
    assert _codes(result) == {"record_missing"}


def test_section_11_3_fixture_passes() -> None:
    result = _check((FIXTURES / "section_11_3_design_record.txt").read_text("utf-8"))
    assert result.issues == ()
    assert result.exit_code == 0
    assert result.failure_mode_rows == 3
    assert result.live_check_command_present is True
    assert result.live_check_failing_reading is True


def test_any_issue_sets_exit_code_nonzero_and_none_sets_zero() -> None:
    good = HEAD + HEADER + "| a | b | c | 1 | GAP |\n"
    assert _check(good).exit_code == 0
    assert _check(HEAD + HEADER).exit_code != 0
    assert _check("nothing").exit_code != 0


def test_issue_count_matches_issues() -> None:
    result = _check(HEAD + HEADER + "| a | b | c | 9 | |\n")
    assert result.record_issue_count == len(result.issues) == 2


def test_every_issue_is_an_error_naming_its_rule() -> None:
    result = _check(HEAD + HEADER + "| a | b | c | 9 | |\n")
    assert {i.rule_name for i in result.issues} == _codes(result)
    assert all(i.severity == EnumSeverity.ERROR for i in result.issues)


def test_committed_contract_holds_every_rule_table() -> None:
    contract = load_design_record_contract()
    assert contract.validator_id == "design_record"
    assert {rule.rule_id for rule in contract.rules} == RULE_IDS
    by_id = {rule.rule_id: rule.parameters or {} for rule in contract.rules}
    assert by_id["severity_out_of_range"]["severity_levels"] == ["1", "2", "3"]
    assert "tbd" in by_id["row_without_detector_or_gap"]["empty_detector_values"]


def test_handler_module_holds_no_rule_table() -> None:
    source = Path(handler_module.__file__).read_text("utf-8")
    for entry in ("tbd", "n/a", "todo", "GAP"):
        assert entry not in source, (
            f"{entry!r} is a rule-table entry: it belongs in the contract"
        )


def test_removing_an_empty_detector_entry_changes_the_verdict() -> None:
    body = HEAD + HEADER + "| a | b | c | 1 | tbd |\n"
    assert _codes(_check(body)) == {"row_without_detector_or_gap"}

    def drop_tbd(rules: dict[str, dict[str, Any]]) -> None:
        params = rules["row_without_detector_or_gap"]["parameters"]
        params["empty_detector_values"].remove("tbd")

    assert _check(body, _contract_with(drop_tbd)).issues == ()


def test_changing_the_gap_pattern_changes_the_verdict() -> None:
    body = HEAD + HEADER + "| a | b | GAP | 1 | none |\n"
    assert _check(body).issues == ()

    def other_mark(rules: dict[str, dict[str, Any]]) -> None:
        rules["row_without_detector_or_gap"]["parameters"]["gap_pattern"] = r"\bHOLE\b"

    assert _codes(_check(body, _contract_with(other_mark))) == {
        "row_without_detector_or_gap"
    }
    hole = HEAD + HEADER + "| a | b | HOLE | 1 | none |\n"
    assert _codes(_check(hole)) == {"row_without_detector_or_gap"}
    assert _check(hole, _contract_with(other_mark)).issues == ()


def test_severity_four_refused_under_committed_and_accepted_under_fixture() -> None:
    body = HEAD + HEADER + "| a | b | c | 4 | probe |\n"
    assert _codes(_check(body)) == {"severity_out_of_range"}

    def add_four(rules: dict[str, dict[str, Any]]) -> None:
        rules["severity_out_of_range"]["parameters"]["severity_levels"].append("4")

    assert _check(body, _contract_with(add_four)).issues == ()


def test_removing_a_severity_level_changes_the_verdict() -> None:
    body = HEAD + HEADER + "| a | b | c | 3 | probe |\n"
    assert _check(body).issues == ()

    def drop_three(rules: dict[str, dict[str, Any]]) -> None:
        rules["severity_out_of_range"]["parameters"]["severity_levels"].remove("3")

    assert _codes(_check(body, _contract_with(drop_three))) == {"severity_out_of_range"}


def test_a_disabled_rule_reports_no_issue_but_keeps_the_fact() -> None:
    body = HEAD + HEADER + "| a | b | c | 1 | none |\n"

    def disable(rules: dict[str, dict[str, Any]]) -> None:
        rules["row_without_detector_or_gap"]["enabled"] = False

    result = _check(body, _contract_with(disable))
    assert result.issues == ()
    assert result.exit_code == 0
    assert result.rows_without_detector_or_gap == 1


def test_a_contract_missing_a_rule_fails_closed() -> None:
    def drop(rules: dict[str, dict[str, Any]]) -> None:
        del rules["severity_out_of_range"]

    with pytest.raises(ModelOnexError, match="severity_out_of_range"):
        _check(HEAD + HEADER, _contract_with(drop))


def test_handler_module_is_pure() -> None:
    tree = ast.parse(Path(handler_module.__file__).read_text("utf-8"))
    imported = {
        alias.name.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    } | {
        node.module.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    }
    assert not imported & {
        "os",
        "pathlib",
        "subprocess",
        "socket",
        "time",
        "datetime",
        "random",
        "urllib",
        "logging",
    }


def test_results_are_byte_identical_in_process_and_through_the_entry() -> None:
    contract = load_design_record_contract()
    for name in ("section_11_3_design_record.txt",):
        text = (FIXTURES / name).read_text("utf-8")
        direct = _check(text, contract).model_dump_json()
        assert _check(text, contract).model_dump_json() == direct
        assert check_design_record_text(text, contract).model_dump_json() == direct
    refused = HEAD + HEADER + "| a | b | c | 9 | |\n"
    assert (
        check_design_record_text(refused, contract).model_dump_json()
        == _check(refused, contract).model_dump_json()
    )


def test_file_validator_reports_issues_at_the_file(tmp_path: Path) -> None:
    good = tmp_path / "good_design_record.md"
    good.write_text((FIXTURES / "section_11_3_design_record.txt").read_text("utf-8"))
    bad = tmp_path / "bad_design_record.md"
    bad.write_text(HEAD + HEADER)
    validator = ValidatorDesignRecord()
    assert validator.validate_file(good).is_valid
    result = validator.validate_file(bad)
    assert not result.is_valid
    assert {issue.file_path for issue in result.issues} == {bad}
    assert {issue.code for issue in result.issues} == {"failure_mode_table_empty"}
