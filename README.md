# Placement Readiness

An AI-powered interview preparation platform that generates company- and
role-specific assessments, evaluates performance across multiple
readiness dimensions, tracks progress over time, and recommends
personalized preparation based on identified skill gaps.

Instead of relying on static question banks or generic preparation
material, the system combines coding, aptitude, resume, and mock
interview assessments into a unified adaptive preparation workflow.

------------------------------------------------------------------------

# Features

-   Company- and role-specific interview preparation
-   AI-generated coding and aptitude assessments
-   Independent validation of generated questions and answers
-   Automated code execution and evaluation
-   AI-powered resume analysis with job-description alignment
-   Personalized mock interview generation and evaluation
-   Multi-dimensional readiness and progress tracking
-   Personalized intervention plans based on identified skill gaps
-   Company and role research using SerpAPI
-   Persistent PostgreSQL storage
-   Dockerized application
-   Cloud deployment on Amazon ECS Fargate

------------------------------------------------------------------------

# Architecture

``` text
                         User
                           │
                           ▼
                    NiceGUI Interface
                           │
                           ▼
               Placement Readiness App
                           │
        ┌──────────────────┼──────────────────┐
        ▼                  ▼                  ▼
 Company / Role       Resume Analysis    Assessment Engine
    Research                                  │
                              ┌───────────────┼───────────────┐
                              ▼               ▼               ▼
                           Coding          Aptitude      Mock Interview
                              │               │               │
                              ▼               ▼               ▼
                         Validation      Validation       Evaluation
                              └───────────────┬───────────────┘
                                              ▼
                                       Amazon Bedrock
                                              │
                                              ▼
                                     Readiness Tracking
                                              │
                                              ▼
                                  Personalized Preparation
```

------------------------------------------------------------------------

# Assessment Workflow

The platform evaluates preparation across coding, aptitude, resume,
communication, project depth, interview performance, consistency, and
coachability.

Coding and aptitude questions are generated dynamically for the selected
company and role, with a separate validation step checking generated
questions before they are presented.

Mock interviews are personalized using the target role, company, resume,
and previous questions. Submitted responses are evaluated for
communication, technical depth, and interview performance.

Resume analysis evaluates the candidate's resume against the selected
role and, when provided, the job description.

Assessment results are stored over time to identify weak areas, track
improvement, and generate focused preparation plans.

------------------------------------------------------------------------

# Running Locally

Create a `.env` file with the required database, AWS Bedrock, SerpAPI,
and application configuration.

Install dependencies:

``` bash
uv sync
```

Run with Docker Compose:

``` bash
docker compose up --build
```

The application is available locally at `http://localhost:8080`.

------------------------------------------------------------------------

# AWS Deployment

The application is containerized using Docker and deployed on Amazon ECS
Fargate.

-   Application and code-runner images are stored in Amazon ECR
-   PostgreSQL is hosted using Amazon RDS
-   Secrets are managed through AWS Secrets Manager
-   IAM task roles provide access to Amazon Bedrock
-   An Application Load Balancer exposes the application
-   Application logs are stored in Amazon CloudWatch

------------------------------------------------------------------------

# Motivation

Interview preparation is often fragmented across coding platforms,
aptitude question banks, resume tools, and mock interview resources.

Placement Readiness combines these workflows into one adaptive system
that evaluates performance, tracks readiness over time, identifies skill
gaps, and recommends what to practice next for a specific company and
role.
