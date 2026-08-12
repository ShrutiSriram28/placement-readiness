from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, model_validator


class ReadinessVector(BaseModel):
    coding: float = Field(ge=0)
    aptitude: float = Field(ge=0)
    resume: float = Field(ge=0)
    communication: float = Field(ge=0)
    project_depth: float = Field(ge=0)
    interview: float = Field(ge=0)
    consistency: float = Field(ge=0)
    coachability: float = Field(ge=0)


class RoleStageOutput(BaseModel):
    name: str
    description: str
    dimensions: list[str] = Field(default_factory=list)


class RoleProfileLLMOutput(BaseModel):
    process_summary: str
    stages: list[RoleStageOutput] = Field(default_factory=list)
    weights: ReadinessVector
    thresholds: ReadinessVector
    caveats: list[str] = Field(default_factory=list)


class ResearchSummaryOutput(BaseModel):
    recurring_topics: list[str] = Field(default_factory=list)
    notable_question_titles: list[str] = Field(default_factory=list)


class CodingTestInput(BaseModel):
    args: list[Any]


class CodingQuestion(BaseModel):
    title: str
    prompt: str
    topic: str
    difficulty: str
    function_name: str
    starter_code: str

    # This is NEVER shown to the student.
    # It is used only to derive trusted hidden-test outputs.
    reference_solution: str

    # The LLM only generates inputs.
    # The runner calculates the expected results.
    tests: list[CodingTestInput] = Field(min_length=5)

    @model_validator(mode="after")
    def validate_code_fields(self):
        function_token = (f"def {self.function_name}(")

        if function_token not in self.starter_code:
            raise ValueError("starter_code must define the exact required function_name")

        if (function_token not in self.reference_solution):
            raise ValueError("reference_solution must define the exact required function_name")

        return self


class CodingQuestionPack(BaseModel):
    questions: list[CodingQuestion]


class CodingQuestionValidation(BaseModel):
    title: str
    valid: bool
    reason: str


class CodingValidationPack(BaseModel):
    validations: list[CodingQuestionValidation]


class AptitudeQuestion(BaseModel):
    title: str
    prompt: str
    topic: str
    difficulty: str
    choices: list[str] = Field(min_length=4, max_length=4)
    correct_choice_index: int = Field(ge=0, le=3)
    explanation: str


class AptitudeQuestionPack(BaseModel):
    questions: list[AptitudeQuestion]


class AptitudeQuestionValidation(BaseModel):
    title: str
    valid: bool
    correct_choice_index: (int | None) = Field(default=None, ge=0, le=3)
    explanation: str
    reason: str
    confidence: float = Field(ge=0, le=1)


class AptitudeValidationPack(BaseModel):
    validations: list[AptitudeQuestionValidation]


class ResumeLLMOutput(BaseModel):
    score: float = Field(ge=0, le=100)
    strengths: list[str] = Field(default_factory=list)
    weaknesses: list[str] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)
    missing_keywords: list[str] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)


class MockInterviewQuestionPack(BaseModel):
    questions: list[str]


class MockInterviewEvaluation(BaseModel):
    communication_score: float = Field(ge=0, le=100)
    project_depth_score: float = Field(ge=0, le=100)
    interview_score: float = Field(ge=0, le=100)
    strengths: list[str] = Field(default_factory=list)
    weaknesses: list[str] = Field(default_factory=list)
    overall_feedback: str


class InterventionPlanOutput(BaseModel):
    title: str
    plan: str
    tasks: list[str] = Field(default_factory=list)
    success_criteria: list[str] = Field(default_factory=list)