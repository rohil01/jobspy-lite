from pydantic import BaseModel, Field, model_validator
from typing import List, Literal, Optional


class ExperienceYearsOutput(BaseModel):
    min_years: int = Field(ge=0)
    max_years: Optional[int] = Field(default=None, ge=0)

    @model_validator(mode="after")
    def check_range(self):
        if self.max_years is not None and self.max_years < self.min_years:
            raise ValueError("max_years must be >= min_years")
        return self


class SuitabilityOutput(BaseModel):
    score: Optional[int] = Field(default=None, ge=0, le=100)
    verdict: Literal["strong", "moderate", "weak"]
    matched_skills: List[str] = Field(default_factory=list)
    missing_skills: List[str] = Field(default_factory=list)
    reasoning: str

    skill_match_ratio: Optional[float] = Field(default=None, ge=0, le=100)
    final_score: Optional[int] = Field(default=None, ge=0, le=100)

    @model_validator(mode="after")
    def compute_final_score(self):
        total_skills = len(self.matched_skills) + len(self.missing_skills)

        if total_skills > 0:
            self.skill_match_ratio = round(
                (len(self.matched_skills) / total_skills) * 100, 1
            )
        else:
            self.skill_match_ratio = None

        # Blend AI score and skill match ratio (equal weight by default)
        if self.score is not None and self.skill_match_ratio is not None:
            self.final_score = round((self.score + self.skill_match_ratio) / 2)
        elif self.score is not None:
            self.final_score = self.score
        elif self.skill_match_ratio is not None:
            self.final_score = round(self.skill_match_ratio)
        else:
            self.final_score = None

        return self
