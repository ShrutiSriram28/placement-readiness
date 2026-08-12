from __future__ import annotations

import json
import os
import re
from typing import TypeVar

from langchain_aws import ChatBedrockConverse
from pydantic import BaseModel, ValidationError

from app.config import settings
from app.schemas import (
    AptitudeQuestionPack,
    AptitudeValidationPack,
    CodingQuestionPack,
    CodingValidationPack,
    InterventionPlanOutput,
    MockInterviewEvaluation,
    MockInterviewQuestionPack,
    ResearchSummaryOutput,
    ResumeLLMOutput,
    RoleProfileLLMOutput,
)


T = TypeVar("T", bound = BaseModel)


class LLMService:
    def __init__(self) -> None:
        region_name = os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION")
        model_id = os.getenv("BEDROCK_MODEL_ID")
        validator_model_id = os.getenv("BEDROCK_VALIDATOR_MODEL_ID") or model_id

        if not region_name:
            raise RuntimeError("AWS_REGION or AWS_DEFAULT_REGION must be configured.")
        if not model_id:
            raise RuntimeError("BEDROCK_MODEL_ID must be configured.")

        generator_max_tokens = int(os.getenv("BEDROCK_MAX_TOKENS", "4096"))
        validator_max_tokens = int(os.getenv("BEDROCK_VALIDATOR_MAX_TOKENS", "3072"))

        self.llm = ChatBedrockConverse(model_id = model_id, region_name = region_name, temperature = 0.35, max_tokens = generator_max_tokens)

        # Used only for independent
        # question/answer validation.
        self.validator_llm = ChatBedrockConverse(model_id = validator_model_id, region_name = region_name, temperature = 0.0, max_tokens = validator_max_tokens)

    def _extract_json(self, content: str) -> str:
        content = content.strip()

        if content.startswith("```"):
            content = re.sub((r"^```" r"(?:json)?\s*"), "", content, flags = re.IGNORECASE)
            content = re.sub(r"\s*```$", "", content)

        first_object = content.find("{")
        last_object = content.rfind("}")

        if (first_object != -1 and last_object != -1 and last_object > first_object):
            content = content[first_object:last_object + 1]

        return content.strip()

    def _invoke_structured(self, prompt: str, schema: type[T], validator: bool = False) -> T:
        schema_dict = schema.model_json_schema()
        schema_json = json.dumps(schema_dict, indent = 2)
        expected_fields = list(schema_dict.get("properties", {}).keys())
        model = self.validator_llm if validator else self.llm
        last_error: Exception | None = None

        for attempt in range(1, 4):
            retry_note = ""

            if attempt > 1:
                retry_note = f"""
Your previous response was invalid.

You MUST now return a populated JSON object for {schema.__name__}.

Do NOT return or describe the schema.
Do NOT return keys such as "properties", "$defs", "required", "title", or "type" unless one of those is explicitly an expected application field.

Expected top-level application fields:
{json.dumps(expected_fields)}

Return actual values for those fields.
"""

            full_prompt = f"""
{prompt}

{retry_note}

OUTPUT CONTRACT:

Return exactly ONE populated JSON object and nothing else.

The object represents one actual {schema.__name__} result.
It is DATA, not a schema definition.

Do NOT:
- return markdown
- return code fences
- explain the JSON
- repeat these instructions
- repeat or paraphrase the JSON schema
- return a JSON Schema document
- return "properties", "$defs", "required", "title", or "type" as schema metadata

Expected top-level application fields:
{json.dumps(expected_fields)}

The returned JSON object must validate against this schema:

{schema_json}

Before responding, check that:
1. You returned actual data rather than the schema.
2. All required top-level fields are present.
3. Field values use the required types.
4. There is no text before or after the JSON object.
"""

            try:
                response = model.invoke(full_prompt)
                content = response.content

                if isinstance(content, list):
                    text_parts = []

                    for block in content:
                        if isinstance(block, str):
                            text_parts.append(block)

                        elif isinstance(block, dict):
                            block_text = block.get("text")

                            if block_text:
                                text_parts.append(str(block_text))

                    content = "".join(text_parts)

                if not isinstance(content, str):
                    raise ValueError("Bedrock returned a non-text response.")

                if not content.strip():
                    raise ValueError("Bedrock returned an empty text response.")

                cleaned = self._extract_json(content)
                parsed = json.loads(cleaned)

                if not isinstance(parsed, dict):
                    raise ValueError(f"Expected a JSON object for {schema.__name__}, but received {type(parsed).__name__}.")

                schema_metadata_keys = {"properties", "$defs", "required", "title", "type"}
                parsed_keys = set(parsed.keys())

                if "properties" in parsed_keys or (
                    parsed.get("type") == "object"
                    and len(parsed_keys & schema_metadata_keys) >= 2
                ):
                    raise ValueError(f"Bedrock returned the JSON schema for {schema.__name__} instead of populated data.")

                missing_expected = [
                    field
                    for field in schema_dict.get("required", [])
                    if field not in parsed
                ]

                if missing_expected:
                    raise ValueError(f"Bedrock omitted required fields for {schema.__name__}: {missing_expected}")

                return schema.model_validate(parsed)

            except (json.JSONDecodeError, ValidationError, ValueError) as exc:
                last_error = exc

                print(
                    f"BEDROCK STRUCTURED OUTPUT attempt {attempt}/3 failed for {schema.__name__}: {exc}",
                    flush = True,
                )

        raise ValueError(
            f"LLM could not produce valid {schema.__name__} output after 3 attempts. Last error: {last_error}"
        )

    def role_profile(self, company: str, role: str, search_results: list[dict]) -> RoleProfileLLMOutput:
        prompt = f"""
You are designing a placement readiness profile.

Company:
{company}

Role:
{role}

SEARCH RESULTS:
{json.dumps(search_results, indent = 2)}

The readiness dimensions are:

coding
aptitude
resume
communication
project_depth
interview
consistency
coachability

Tasks:

1. Infer likely interview and hiring stages.

2. Identify which readiness dimensions matter at each stage.

3. Produce relative readiness weights.

4. Produce reasonable minimum thresholds from 0 to 100.

5. Give irrelevant dimensions weight 0.

6. Do not present uncertain company-specific information as certain.

7. Mention uncertainty in caveats.

8. Do not assign weight only because a stage happens multiple times.

9. Consider elimination risk and stage importance.

10. Include all eight readiness keys in both weights and thresholds.

OUTPUT CONTENT REQUIREMENTS:

- process_summary must be a concise summary of the likely process.
- stages must contain actual stage objects, not descriptions of the schema.
- weights must contain numeric values for every readiness dimension.
- thresholds must contain numeric values for every readiness dimension.
- caveats must be a list of actual uncertainty statements.
"""

        return self._invoke_structured(prompt, RoleProfileLLMOutput)

    def summarize_question_research(self, company: str, role: str, search_results: list[dict]) -> ResearchSummaryOutput:
        prompt = f"""
Analyze web-search evidence about interview questions.

Company:
{company}

Role:
{role}

SEARCH RESULTS:
{json.dumps(search_results, indent = 2)}

Identify:

1. Recurring technical, coding, aptitude, and interview topics.

2. Question/problem titles explicitly supported by the supplied search results.

Do not invent titles.

Do not reproduce complete copyrighted problem statements.

OUTPUT CONTENT REQUIREMENTS:

- recurring_topics must contain actual topic strings.
- notable_question_titles must contain actual supported titles.
- If no supported titles exist, return an empty list rather than inventing any.
"""

        return self._invoke_structured(prompt, ResearchSummaryOutput)

    def generate_coding_questions(self, company: str, role: str, research: dict, question_count: int, previous_titles: list[str] | None = None, previous_prompts: list[str] | None = None) -> CodingQuestionPack:
        previous_titles = previous_titles or []
        previous_prompts = previous_prompts or []

        prompt = f"""
Create exactly {question_count} NEW, internally consistent Python coding assessment questions.

Target company:
{company}

Target role:
{role}

Internet research:
{json.dumps(research, indent = 2)}

Previously generated titles:
{json.dumps(previous_titles, indent = 2)}

Previously generated prompts:
{json.dumps(previous_prompts, indent = 2)}

NOVELTY REQUIREMENT:

Do not duplicate, lightly reword, or preserve the same underlying problem as a previous question.

Changing only:
- names
- numbers
- variable names
- story context

does NOT count as a new question.

Rotate:
- algorithmic pattern
- data structure
- input structure
- edge cases
- difficulty

CORRECTNESS REQUIREMENTS:

Every question must satisfy ALL of these conditions.

1. The prompt is self-contained.

2. The prompt has one clear interpretation.

3. The problem defines exactly one Python function.

4. function_name, starter_code, reference_solution, and prompt all agree.

5. reference_solution is a COMPLETE and CORRECT implementation.

6. reference_solution must define exactly the requested function.

7. Generate at least FIVE deterministic test INPUTS.

8. Each test contains only:
   args

9. DO NOT provide expected outputs.

The backend will execute the reference solution and derive the expected outputs itself.

10. Include normal and edge cases.

11. Arguments and return values must be JSON-compatible.

12. Do not require:
    stdin
    stdout
    files
    network
    randomness
    external packages
    input()
    interactive input

13. The reference solution must not import anything.

14. Avoid problems whose answer depends on:
    unspecified tie breaking
    dictionary ordering
    set ordering
    floating-point tolerance
    time
    locale
    randomness

15. If ordering matters, state it explicitly.

16. If rounding matters, state it explicitly.

17. Make the difficulty label realistic.

The reference solution is validation metadata only and will never be displayed to the student.

OUTPUT CONTENT REQUIREMENTS:

- questions must contain exactly {question_count} actual coding-question objects.
- Do not return field definitions or schema descriptions.
- Each question must contain a real title, prompt, topic, difficulty, function_name, starter_code, reference_solution, and tests.
- tests must contain actual argument values.
"""

        return self._invoke_structured(prompt, CodingQuestionPack)

    def validate_coding_questions(self, pack: CodingQuestionPack) -> CodingValidationPack:
        candidates = []

        for question in pack.questions:
            candidates.append(
                {
                    "title": question.title,
                    "prompt": question.prompt,
                    "topic": question.topic,
                    "difficulty": question.difficulty,
                    "function_name": question.function_name,
                    "starter_code": question.starter_code,
                    "reference_solution": question.reference_solution,
                    "tests": [test.model_dump() for test in question.tests],
                }
            )

        prompt = f"""
Act as an independent coding-assessment validator.

Do NOT assume the generator is correct.

Review every candidate below.

CANDIDATES:

{json.dumps(candidates, indent = 2)}

For every candidate return one validation with the exact same title.

Mark valid=true ONLY when ALL conditions below are true:

1. The problem statement is complete and unambiguous.

2. The requested function signature matches the problem statement.

3. starter_code defines the exact required function.

4. reference_solution defines the exact required function.

5. The reference solution actually solves the described problem.

6. Every test input is legal under the stated problem.

7. No test depends on unspecified behavior.

8. The function result is deterministic.

9. The result is JSON-compatible.

10. There is no contradiction between the prompt, constraints, examples, and reference solution.

11. The question is appropriate for a coding assessment.

If anything is questionable, mark valid=false.

Do not be lenient.

OUTPUT CONTENT REQUIREMENTS:

- validations must contain exactly one validation per candidate.
- Preserve candidate order.
- Every validation must contain the candidate's exact title.
- valid must be an actual boolean.
- reason must explain the decision.
- Do not return the schema.
"""

        return self._invoke_structured(prompt, CodingValidationPack, validator = True)

    def generate_aptitude_questions(self, company: str, role: str, research: dict, question_count: int, previous_titles: list[str] | None = None, previous_prompts: list[str] | None = None) -> AptitudeQuestionPack:
        previous_titles = previous_titles or []
        previous_prompts = previous_prompts or []

        prompt = f"""
Create exactly {question_count} NEW aptitude questions for placement preparation.

Target company:
{company}

Target role:
{role}

Internet research:
{json.dumps(research, indent = 2)}

Previously generated titles:
{json.dumps(previous_titles, indent = 2)}

Previously generated prompts:
{json.dumps(previous_prompts, indent = 2)}

Do not duplicate or lightly reword previous questions.

Changing only names, numbers, units, or story context is not enough.

Use an appropriate mix of:
- quantitative aptitude
- logical reasoning
- probability
- data interpretation
- analytical reasoning

CORRECTNESS REQUIREMENTS:

1. Every question must be completely solvable using only the provided information.

2. Exactly four choices.

3. Exactly ONE choice must be correct.

4. correct_choice_index must be 0, 1, 2, or 3.

5. explanation must actually derive the stated answer.

6. Check every arithmetic operation before returning.

7. Do not create questions where two rounded choices could both be defensible.

8. State units whenever necessary.

9. State assumptions whenever necessary.

10. State rounding rules whenever necessary.

11. State ordering rules whenever necessary.

12. Do not make the correct answer depend on missing context.

OUTPUT CONTENT REQUIREMENTS:

- questions must contain exactly {question_count} actual aptitude-question objects.
- Every question must have four real answer choices.
- correct_choice_index must correspond to the truly correct option.
- explanation must show the reasoning used to obtain that answer.
- Do not return field definitions or schema metadata.
"""

        return self._invoke_structured(prompt, AptitudeQuestionPack)

    def validate_aptitude_questions(self, pack: AptitudeQuestionPack) -> AptitudeValidationPack:
        candidates = [
            {
                "title": question.title,
                "prompt": question.prompt,
                "topic": question.topic,
                "difficulty": question.difficulty,
                "choices": question.choices,
            }
            for question in pack.questions
        ]

        prompt = f"""
You are an independent aptitude-test answer-key validator.

Solve each question from scratch.

IMPORTANT:

You are deliberately NOT being shown the generator's proposed correct answer.

QUESTIONS:

{json.dumps(candidates, indent = 2)}

For every question:

1. Determine whether it is valid and unambiguous.

2. Solve it independently.

3. Return correct_choice_index only when exactly one supplied answer choice is correct.

4. Give a concise explanation that actually demonstrates the calculation or reasoning.

5. Set valid=false when:
   information is missing
   more than one answer is defensible
   no supplied option is correct
   wording is contradictory
   units are ambiguous
   rounding is ambiguous

6. confidence must reflect certainty.

7. valid=true is allowed only when confidence >= 0.90.

Return validations in exactly the same order as the supplied questions.

OUTPUT CONTENT REQUIREMENTS:

- validations must contain exactly one populated validation object per supplied question.
- Preserve the exact title and order.
- correct_choice_index must be null only when the question is invalid.
- valid, confidence, explanation, and reason must contain actual values.
- Do not return or describe the validation schema.
"""

        return self._invoke_structured(prompt, AptitudeValidationPack, validator = True)

    def resume_analysis(self, resume_text: str, company: str, role: str, job_description: str, role_profile: dict | None) -> ResumeLLMOutput:
        prompt = f"""
Evaluate the student's resume for the supplied target.

TARGET COMPANY:
{company}

TARGET ROLE:
{role}

JOB DESCRIPTION:
{job_description or "No job description supplied."}

ROLE PROFILE:
{json.dumps(role_profile or {}, indent = 2)}

RESUME:
{resume_text}

Use:

1. role relevance
2. technical evidence
3. measurable impact
4. project/experience depth
5. clarity
6. job-description alignment

Score from 0 to 100.

Do not reward keyword stuffing.

Do not invent experience.

Recommendations must preserve truthfulness.

OUTPUT CONTENT REQUIREMENTS:

Return an actual resume evaluation.

- score must be one numeric score from 0 to 100.
- strengths must contain concrete strengths supported by the resume.
- weaknesses must contain concrete weaknesses or gaps.
- recommendations must contain actionable truthful changes.
- missing_keywords must contain only genuinely relevant missing terms; use an empty list if none are important.
- evidence must cite actual resume evidence or missing evidence used to justify the score.
- Do not return descriptions of these fields.
- Do not return the schema.
"""

        return self._invoke_structured(prompt, ResumeLLMOutput)

    def generate_mock_interview(self, company: str, role: str, interview_type: str, resume_text: str, role_profile: dict | None, question_count: int = 6, previous_questions: list[str] | None = None) -> MockInterviewQuestionPack:
        previous_questions = previous_questions or []

        prompt = f"""
Generate exactly {question_count} NEW interview questions.

Company:
{company}

Role:
{role}

Interview type:
{interview_type}

ROLE PROFILE:
{json.dumps(role_profile or {}, indent = 2)}

STUDENT RESUME:
{resume_text}

PREVIOUSLY GENERATED QUESTIONS:
{json.dumps(previous_questions, indent = 2)}

Do not repeat or lightly reword a previous question.

A new question must probe a meaningfully different:
decision
scenario
tradeoff
failure mode
constraint
experience

For project-depth interviews, rotate across:
architecture
database choices
model choices
APIs
scalability
latency
reliability
security
deployment
evaluation
debugging
limitations
alternatives
data quality
edge cases
personal contribution
changed constraints

For behavioral/general interviews rotate across:
ownership
conflict
failure
ambiguity
prioritization
collaboration
leadership
feedback
deadlines
mistakes
initiative

Do not invent resume experience.

Do not provide answers.

OUTPUT CONTENT REQUIREMENTS:

- questions must be a list containing exactly {question_count} actual interview-question strings.
- Every item must be a complete question that can be asked directly to the candidate.
- Do not return objects describing questions.
- Do not return a schema.
- Do not return sample field definitions.
"""

        return self._invoke_structured(prompt, MockInterviewQuestionPack)

    def evaluate_mock_interview(self, company: str, role: str, interview_type: str, questions: list[str], answers: list[str], resume_text: str) -> MockInterviewEvaluation:
        qa_pairs = [
            {
                "question": question,
                "answer": answer,
            }
            for question, answer in zip(questions, answers)
        ]

        prompt = f"""
Evaluate this TEXT-BASED mock interview.

Company:
{company}

Role:
{role}

Interview type:
{interview_type}

RESUME CONTEXT:
{resume_text}

QUESTION/ANSWER PAIRS:
{json.dumps(qa_pairs, indent = 2)}

Do not evaluate:
voice
accent
eye contact
vocal tone
body language
spoken fluency

Evaluate communication using:
clarity
logical structure
relevance
completeness
concision

Evaluate project depth using:
technical understanding
design reasoning
tradeoffs
alternatives
failure analysis
limitations
ability to defend choices

Evaluate interview performance using:
directness
specificity
reasoning
examples
ability to respond to probing
completeness

Be demanding.

Do not inflate polished but shallow responses.

OUTPUT CONTENT REQUIREMENTS:

- communication_score must be a real numeric score from 0 to 100.
- project_depth_score must be a real numeric score from 0 to 100.
- interview_score must be a real numeric score from 0 to 100.
- strengths must contain evidence-based strengths from the supplied answers.
- weaknesses must contain evidence-based weaknesses from the supplied answers.
- overall_feedback must be a concise actual evaluation.
- Do not return field descriptions or schema metadata.
"""

        return self._invoke_structured(prompt, MockInterviewEvaluation, validator = True)

    def intervention_plan(self, company: str, role: str, bottleneck: str, current_score: float | None, threshold: float | None, trend: str) -> InterventionPlanOutput:
        prompt = f"""
Create a focused two-week placement preparation plan.

Company:
{company}

Role:
{role}

Primary bottleneck:
{bottleneck}

Current score:
{current_score}

Target threshold:
{threshold}

Recent trend:
{trend}

Focus primarily on the current bottleneck.

Tasks must be:
concrete
measurable
achievable in two weeks

The plan must end with a reassessment.

OUTPUT CONTENT REQUIREMENTS:

- title must be a concise actual plan title.
- plan must contain the overall two-week strategy.
- tasks must contain concrete actions the student can complete.
- success_criteria must contain measurable criteria for determining whether the intervention worked.
- The final task or success criterion must include reassessment.
- Do not return field definitions.
- Do not return the schema.
"""

        return self._invoke_structured(prompt, InterventionPlanOutput)


llm_service = LLMService()