# eval-runner/reporter.py

def generate_report(scenario: dict, results: list):
    """
    Generates and prints a summary report of the evaluation results.

    Args:
        scenario: The dictionary of the scenario that was run.
        results: The list of results from the evaluation engine.
    """
    print("\n" + "="*50)
    print("EVALUATION REPORT")
    print("="*50)
    print(f"Scenario: {scenario.get('title')} ({scenario.get('scenario_id')})")
    print(f"Industry: {scenario.get('industry')}")
    print(f"Description: {scenario.get('description')}")
    print("-"*50)

    total_tasks = len(results)
    successful_tasks = 0

    for task_result in results:
        task_id = task_result["task_id"]
        
        # A task is successful if all its metric criteria are met
        task_is_overall_success = all(m['success'] for m in task_result['metrics'])
        
        if task_is_overall_success:
            successful_tasks += 1
            status = "✅ SUCCESS"
        else:
            status = "❌ FAILURE"
            
        print(f"\n▶️ Task: {task_id} [{status}]")
        
        for metric in task_result['metrics']:
            metric_status = "✅" if metric['success'] else "❌"
            print(
                f"  {metric_status} Metric: {metric['metric']:<35} "
                f"| Score: {metric['score']:.2f} "
                f"| Threshold: {metric['threshold']:.2f}"
            )

    print("\n" + "-"*50)
    print("SUMMARY")
    print("-"*50)
    
    success_rate = (successful_tasks / total_tasks) * 100 if total_tasks > 0 else 0
    
    print(f"Total Tasks: {total_tasks}")
    print(f"Successful Tasks: {successful_tasks}")
    print(f"Failed Tasks: {total_tasks - successful_tasks}")
    print(f"Overall Success Rate: {success_rate:.2f}%")
    print("="*50 + "\n")
