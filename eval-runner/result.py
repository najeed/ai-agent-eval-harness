"""
result.py

This module provides the EvaluationResult class for the AI Agent Evaluation Harness.
It encapsulates evaluation results and provides export functionality to CSV, JSON, and HTML formats.

Typical usage example:
    from eval_runner import result
    results = result.EvaluationResult(scenario_data, task_results)
    results.export_csv("results.csv")
    results.export_json("results.json")
    results.export_html("report.html", include_charts=True)
"""

import csv
import json
import os
from datetime import datetime
from typing import Dict, List, Any, Optional


class EvaluationResult:
    """
    Encapsulates evaluation results and provides export functionality.
    
    This class wraps the evaluation results from the engine and provides
    methods to export the data in various formats (CSV, JSON, HTML).
    """
    
    def __init__(self, scenario: Dict[str, Any], task_results: List[Dict[str, Any]]):
        """
        Initialize EvaluationResult with scenario and task results.
        
        Args:
            scenario (dict): The scenario dictionary containing scenario metadata
            task_results (list): List of task result dictionaries from the engine
        """
        self.scenario = scenario
        self.task_results = task_results
        self.timestamp = datetime.now().isoformat()
        
    def get_summary_stats(self) -> Dict[str, Any]:
        """
        Calculate summary statistics for the evaluation results.
        
        Returns:
            dict: Summary statistics including total tasks, successful tasks, and success rate
        """
        total_tasks = len(self.task_results)
        successful_tasks = sum(1 for task in self.task_results 
                             if all(m["success"] for m in task.get("metrics", [])))
        success_rate = (successful_tasks / total_tasks) * 100 if total_tasks > 0 else 0
        
        return {
            "total_tasks": total_tasks,
            "successful_tasks": successful_tasks,
            "failed_tasks": total_tasks - successful_tasks,
            "success_rate": success_rate
        }
    
    def _flatten_metrics_for_csv(self) -> List[Dict[str, Any]]:
        """
        Flatten the nested task and metrics structure for CSV export.
        
        Returns:
            list: List of flattened dictionaries suitable for CSV writing
        """
        flattened_data = []
        
        for task in self.task_results:
            task_id = task.get("task_id", "")
            
            for metric in task.get("metrics", []):
                row = {
                    "scenario_id": self.scenario.get("scenario_id", ""),
                    "scenario_title": self.scenario.get("title", ""),
                    "scenario_description": self.scenario.get("description", ""),
                    "industry": self.scenario.get("industry", ""),
                    "task_id": task_id,
                    "metric_name": metric.get("metric", ""),
                    "score": metric.get("score", 0),
                    "threshold": metric.get("threshold", 0),
                    "success": metric.get("success", False),
                    "timestamp": self.timestamp
                }
                flattened_data.append(row)
        
        return flattened_data
    
    def export_csv(self, filepath: str) -> None:
        """
        Export evaluation results to CSV format.
        
        Args:
            filepath (str): Path to save the CSV file
            
        Raises:
            IOError: If file cannot be written
        """
        flattened_data = self._flatten_metrics_for_csv()
        
        if not flattened_data:
            raise ValueError("No data to export")
        
        # Ensure directory exists
        os.makedirs(os.path.dirname(os.path.abspath(filepath)), exist_ok=True)
        
        with open(filepath, 'w', newline='', encoding='utf-8') as csvfile:
            fieldnames = flattened_data[0].keys()
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            
            writer.writeheader()
            writer.writerows(flattened_data)
        
        print(f"✅ CSV export completed: {filepath}")
    
    def export_json(self, filepath: str) -> None:
        """
        Export evaluation results to JSON format.
        
        Args:
            filepath (str): Path to save the JSON file
            
        Raises:
            IOError: If file cannot be written
        """
        # Create a comprehensive JSON structure
        export_data = {
            "metadata": {
                "export_timestamp": self.timestamp,
                "scenario_id": self.scenario.get("scenario_id", ""),
                "scenario_title": self.scenario.get("title", ""),
                "industry": self.scenario.get("industry", ""),
                "description": self.scenario.get("description", "")
            },
            "summary": self.get_summary_stats(),
            "scenario": self.scenario,
            "task_results": self.task_results
        }
        
        # Ensure directory exists
        os.makedirs(os.path.dirname(os.path.abspath(filepath)), exist_ok=True)
        
        with open(filepath, 'w', encoding='utf-8') as jsonfile:
            json.dump(export_data, jsonfile, indent=2, ensure_ascii=False)
        
        print(f"✅ JSON export completed: {filepath}")
    
    def export_html(self, filepath: str, include_charts: bool = False) -> None:
        """
        Export evaluation results to HTML format.
        
        Args:
            filepath (str): Path to save the HTML file
            include_charts (bool): Whether to include basic visualization charts
            
        Raises:
            IOError: If file cannot be written
        """
        summary = self.get_summary_stats()
        
        # Generate HTML content
        html_content = self._generate_html_content(summary, include_charts)
        
        # Ensure directory exists
        os.makedirs(os.path.dirname(os.path.abspath(filepath)), exist_ok=True)
        
        with open(filepath, 'w', encoding='utf-8') as htmlfile:
            htmlfile.write(html_content)
        
        print(f"✅ HTML export completed: {filepath}")
    
    def _generate_html_content(self, summary: Dict[str, Any], include_charts: bool) -> str:
        """
        Generate HTML content for the report.
        
        Args:
            summary (dict): Summary statistics
            include_charts (bool): Whether to include charts
            
        Returns:
            str: Complete HTML content
        """
        # Basic CSS styling
        css_styles = """
        <style>
            body { font-family: Arial, sans-serif; margin: 40px; line-height: 1.6; }
            .header { background-color: #f4f4f4; padding: 20px; border-radius: 5px; margin-bottom: 30px; }
            .summary { background-color: #e8f5e8; padding: 15px; border-radius: 5px; margin-bottom: 20px; }
            .task-section { margin-bottom: 30px; }
            table { border-collapse: collapse; width: 100%; margin-bottom: 20px; }
            th, td { border: 1px solid #ddd; padding: 12px; text-align: left; }
            th { background-color: #f2f2f2; font-weight: bold; }
            .success { color: #28a745; font-weight: bold; }
            .failure { color: #dc3545; font-weight: bold; }
            .metric-success { background-color: #d4edda; }
            .metric-failure { background-color: #f8d7da; }
            .chart-container { margin: 20px 0; text-align: center; }
        </style>
        """
        
        # Chart script (if needed)
        chart_script = ""
        if include_charts:
            chart_script = self._generate_chart_script(summary)
        
        # HTML body content
        html_body = f"""
        <div class="header">
            <h1>Evaluation Report</h1>
            <p><strong>Scenario:</strong> {self.scenario.get('title', 'N/A')} ({self.scenario.get('scenario_id', 'N/A')})</p>
            <p><strong>Industry:</strong> {self.scenario.get('industry', 'N/A')}</p>
            <p><strong>Description:</strong> {self.scenario.get('description', 'N/A')}</p>
            <p><strong>Generated:</strong> {self.timestamp}</p>
        </div>
        
        <div class="summary">
            <h2>Summary</h2>
            <p><strong>Total Tasks:</strong> {summary['total_tasks']}</p>
            <p><strong>Successful Tasks:</strong> <span class="success">{summary['successful_tasks']}</span></p>
            <p><strong>Failed Tasks:</strong> <span class="failure">{summary['failed_tasks']}</span></p>
            <p><strong>Success Rate:</strong> {summary['success_rate']:.2f}%</p>
        </div>
        """
        
        # Add chart if requested
        if include_charts:
            html_body += f"""
            <div class="chart-container">
                <h3>Success Rate Visualization</h3>
                <canvas id="successChart" width="400" height="200"></canvas>
            </div>
            """
        
        # Task details section
        html_body += "<div class=\"task-section\"><h2>Task Details</h2>"
        
        for task in self.task_results:
            task_id = task.get("task_id", "")
            task_success = all(m["success"] for m in task.get("metrics", []))
            status_class = "success" if task_success else "failure"
            status_text = "SUCCESS" if task_success else "FAILURE"
            
            html_body += f"""
            <h3>Task: {task_id} <span class="{status_class}">[{status_text}]</span></h3>
            <table>
                <thead>
                    <tr>
                        <th>Metric</th>
                        <th>Score</th>
                        <th>Threshold</th>
                        <th>Status</th>
                    </tr>
                </thead>
                <tbody>
            """
            
            for metric in task.get("metrics", []):
                metric_class = "metric-success" if metric["success"] else "metric-failure"
                status_symbol = "✅" if metric["success"] else "❌"
                
                html_body += f"""
                    <tr class="{metric_class}">
                        <td>{metric.get('metric', 'N/A')}</td>
                        <td>{metric.get('score', 0):.2f}</td>
                        <td>{metric.get('threshold', 0):.2f}</td>
                        <td>{status_symbol}</td>
                    </tr>
                """
            
            html_body += "</tbody></table>"
        
        html_body += "</div>"
        
        # Complete HTML document
        html_content = f"""
        <!DOCTYPE html>
        <html lang="en">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>AI Agent Evaluation Report</title>
            {css_styles}
        </head>
        <body>
            {html_body}
            {chart_script}
        </body>
        </html>
        """
        
        return html_content
    
    def _generate_chart_script(self, summary: Dict[str, Any]) -> str:
        """
        Generate JavaScript for basic chart visualization.
        
        Args:
            summary (dict): Summary statistics
            
        Returns:
            str: JavaScript code for chart rendering
        """
        return f"""
        <script>
            // Simple canvas-based chart
            const canvas = document.getElementById('successChart');
            if (canvas) {{
                const ctx = canvas.getContext('2d');
                const successful = {summary['successful_tasks']};
                const failed = {summary['failed_tasks']};
                const total = successful + failed;
                
                // Draw simple bar chart
                const barWidth = 80;
                const barSpacing = 100;
                const maxHeight = 150;
                
                // Success bar
                const successHeight = total > 0 ? (successful / total) * maxHeight : 0;
                ctx.fillStyle = '#28a745';
                ctx.fillRect(50, 200 - successHeight, barWidth, successHeight);
                ctx.fillStyle = '#000';
                ctx.fillText('Success: ' + successful, 50, 220);
                
                // Failure bar
                const failureHeight = total > 0 ? (failed / total) * maxHeight : 0;
                ctx.fillStyle = '#dc3545';
                ctx.fillRect(50 + barSpacing, 200 - failureHeight, barWidth, failureHeight);
                ctx.fillStyle = '#000';
                ctx.fillText('Failed: ' + failed, 50 + barSpacing, 220);
                
                // Title
                ctx.font = '16px Arial';
                ctx.fillText('Task Results', 100, 30);
            }}
        </script>
        """
    
    # Backward compatibility: allow the class to be used like the original list
    def __iter__(self):
        """Allow iteration over task results for backward compatibility."""
        return iter(self.task_results)
    
    def __getitem__(self, index):
        """Allow indexing for backward compatibility."""
        return self.task_results[index]
    
    def __len__(self):
        """Allow len() function for backward compatibility."""
        return len(self.task_results)
