<!-- docs/guides/01_EVALUATION_GUIDE.md -->

# Evaluation Guide

This guide explains the philosophy behind our evaluation scenarios and how to interpret them.

## Scenario Structure

Each evaluation is defined by a `.json` file in an industry's `scenarios` directory. The file has the following top-level keys:

-   `scenario_id`: A unique identifier for the scenario (e.g., `telecom-cs-001`).
-   `title`: A human-readable title.
-   `description`: A brief explanation of the overall goal of the scenario.
-   `use_case`: The specific business function being tested (e.g., `Customer Service`).
-   `industry`: The industry this scenario belongs to.
-   `tasks`: An array of task objects that represent the steps an agent must take to complete the scenario.

## Task Structure

Each object in the `tasks` array represents a single step and contains:

-   `task_id`: A unique ID for the task within the scenario (e.g., `task-1`).
-   `description`: A clear description of what the agent needs to accomplish.
-   `expected_outcome`: A description of what a successful completion of the task looks like.
-   `required_tools`: A list of tool/API names that the agent is expected to use for this task.
-   `success_criteria`: An array defining how to measure success.

## Success Criteria & Metrics

Each object in the `success_criteria` array links a metric to a threshold:

-   `metric`: The name of the metric to calculate (must correspond to a function in `eval-runner/metrics.py`).
-   `threshold`: The minimum score (from 0.0 to 1.0) required to pass this criterion.

A task is only considered successful if **all** of its success criteria are met.
