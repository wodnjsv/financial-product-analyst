"""Closed, server-owned normalization for approved personal condition meanings."""

from pathlib import Path
from typing import Literal

from pydantic import model_validator

from financial_agent.contracts.base import ContractModel


POLICY_PATH = Path('config/intent/personal-condition-policy.v1.json')


class PersonalConditionPolicy(ContractModel):
    policy_version: Literal['personal-condition-policy.v1']
    region_japan: Literal['Japan']
    asset_class_equity: Literal['Equity']
    credit_threshold: Literal['AA-']
    credit_threshold_operator: Literal['gte']
    credit_threshold_values: tuple[str, ...]
    credit_threshold_policy_id: Literal['personal-credit-grade-aa-minus.v1']
    bond_saleability_policy_id: Literal['personal-organizer-bond-saleability.v1']
    bond_saleability_family: Literal['domestic_bond']
    bond_saleability_condition: Literal['purchasable']
    bond_saleability_cutoff_source: Literal['validated_dataset_cutoff']
    bond_saleability_maturity_operator: Literal['gt']
    bond_saleability_remaining_days_operator: Literal['gt']
    bond_saleability_remaining_days_value: Literal['0']

    @model_validator(mode='after')
    def require_approved_credit_order(self):
        if self.credit_threshold_values != ('AAA', 'AA+', 'AA0', 'AA-'):
            raise ValueError('PERSONAL_CREDIT_GRADE_POLICY_MISMATCH')
        return self


def load_personal_condition_policy(project_root: Path | None = None) -> PersonalConditionPolicy:
    root = project_root or Path(__file__).resolve().parents[3]
    return PersonalConditionPolicy.model_validate_json((root / POLICY_PATH).read_bytes())


CONDITION_LITERAL_CONCEPTS = {
    'region': 'region',
    'asset_class': 'asset_class',
    'credit_grade': 'credit_grade',
    'availability_status': 'availability_status',
    'currency': 'currency',
}
