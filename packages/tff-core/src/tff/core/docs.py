"""Dashboard compiler and HTML template generator for Transformation Fitness Functions."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

from tff.core.config import load_fitness_config
from tff.core.context import set_ff_config
from tff.core.health import calculate_health_scores
from tff.core.logs import collect_stats, get_health_json_data, save_log
from tff.core.utils.paths import model_path_relative


def generate_docs_dashboard(
    project_root: Path,
    output_path: Path | None = None,
    provider: str = "auto",
    dialect: str | None = None,
    config_path: str = "fitness_functions.yaml",
) -> Path:
    """Run checks, compile, and output a standalone interactive HTML dashboard."""
    # 1. Load config
    config = load_fitness_config(project_root, config_path=config_path)
    set_ff_config(config)

    # 2. Get runner
    from tff.core.cli import _get_runner
    runner_module = _get_runner(provider)

    # 3. Load models mapping
    models = {}
    if provider == "dbt":
        from tff.dbt.manifest import load_dbt_models
        models = load_dbt_models(project_root, dialect=dialect)
    else:
        from sqlmesh.core.context import Context
        from tff.sqlmesh.loader import FitnessLoader
        from tff.sqlmesh.runner import map_sqlmesh_context_models
        context = Context(
            paths=[str(project_root)],
            loader=FitnessLoader,
        )
        models = map_sqlmesh_context_models(context)

    # 4. Run all checks
    if provider == "dbt":
        findings, models_checked, executed_checks = runner_module.run_all_checks(
            project_root=project_root,
            config=config,
            dialect=dialect,
        )
    else:
        findings, models_checked, executed_checks = runner_module.run_all_checks(
            project_root=project_root,
            config=config,
        )

    # 5. Calculate scores and save health log
    scores = calculate_health_scores(findings, models_checked, config, provider)
    json_data = get_health_json_data(scores, models_checked)
    save_log(project_root, "health", json_data)

    # 6. Collect history (60 days)
    history = collect_stats(project_root, days=60)
    if not history:
        history = [{
            "date": date.today().isoformat(),
            "health_score": scores["overall_score"],
            "errors_count": len([f for f in findings if f.severity == "error"]),
            "warnings_count": len([f for f in findings if f.severity == "warning"]),
        }]

    # 7. Prep data for the HTML template
    rel_to_model_id = {model_path_relative(m): m_id for m_id, m in models.items() if m.path}
    name_to_model_id = {m.name: m_id for m_id, m in models.items()}

    model_findings_serialized: dict[str, list[dict[str, Any]]] = {}
    project_findings: list[dict[str, Any]] = []

    for f in findings:
        serialized_f = {
            "check": f.check,
            "severity": f.severity,
            "message": f.message,
            "path": f.path,
        }

        # Try finding by path first, fallback to name
        m_id = None
        if f.path:
            m_id = rel_to_model_id.get(f.path)
        if not m_id and f.model:
            m_id = name_to_model_id.get(f.model)

        if m_id:
            if m_id not in model_findings_serialized:
                model_findings_serialized[m_id] = []
            model_findings_serialized[m_id].append(serialized_f)
        else:
            project_findings.append(serialized_f)

    # Serialize models
    serialized_models = {}
    for m_id, m in models.items():
        m_findings = model_findings_serialized.get(m_id, [])
        status = "pass"
        if any(f["severity"] == "error" for f in m_findings):
            status = "error"
        elif any(f["severity"] == "warning" for f in m_findings):
            status = "warning"

        serialized_models[m_id] = {
            "id": m_id,
            "name": m.name,
            "path": model_path_relative(m),
            "materialized": m.materialized,
            "owner": m.owner,
            "description": m.description,
            "grains": m.grains,
            "depends_on": list(m.depends_on),
            "is_external": m.is_external,
            "is_symbolic": m.is_symbolic,
            "findings": m_findings,
            "status": status,
        }

    # 8. Render HTML
    data_to_embed = {
        "overall_score": scores["overall_score"],
        "category_scores": scores["category_scores"],
        "models": serialized_models,
        "project_findings": project_findings,
        "history": history,
        "provider": provider,
        "generated_at": json_data["timestamp"],
    }

    embedded_json = json.dumps(data_to_embed, indent=2)
    html_content = HTML_TEMPLATE.replace("<!-- INSERT_TFF_DATA_HERE -->", f"const TFF_DATA = {embedded_json};")

    if output_path is None:
        output_path = project_root / "tff_report.html"
    else:
        if not output_path.is_absolute():
            output_path = project_root / output_path

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html_content)

    return output_path


HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en" class="h-full bg-gray-50">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>TFF Health & Documentation Dashboard</title>
  
  <!-- Tailwind CSS -->
  <script src="https://cdn.tailwindcss.com"></script>
  
  <!-- vis.js Network -->
  <script type="text/javascript" src="https://unpkg.com/vis-network/standalone/umd/vis-network.min.js"></script>
  
  <!-- Chart.js -->
  <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>

  <style>
    #lineage-network {
      width: 100%;
      height: 100%;
      background-color: #ffffff;
    }
    .vis-network:focus {
      outline: none;
    }
  </style>
</head>
<body class="h-full flex flex-col text-gray-900 overflow-hidden font-sans">

  <!-- Header -->
  <header class="bg-slate-900 text-white px-6 py-4 flex items-center justify-between shadow-md shrink-0">
    <div class="flex items-center space-x-3">
      <div class="text-2xl font-black tracking-wider text-cyan-400">TFF</div>
      <div class="h-6 w-[1px] bg-slate-700"></div>
      <h1 class="text-lg font-bold tracking-tight">Fitness Functions Dashboard</h1>
      <span class="bg-cyan-500/10 text-cyan-400 px-2 py-0.5 rounded text-xs font-semibold capitalize" id="provider-badge">...</span>
    </div>
    <div class="text-xs text-slate-400">
      Generated at: <span id="generation-timestamp" class="font-mono">...</span>
    </div>
  </header>

  <!-- Main Container -->
  <main class="flex-1 flex flex-col overflow-hidden">
    
    <!-- Tab Navigation -->
    <div class="bg-white border-b border-gray-200 px-6 py-2 flex items-center justify-between shrink-0">
      <div class="flex space-x-4">
        <button id="btn-tab-lineage" onclick="switchTab('lineage')" class="px-3 py-2 text-sm font-semibold border-b-2 border-indigo-600 text-indigo-600 focus:outline-none">
          Lineage Graph
        </button>
        <button id="btn-tab-findings" onclick="switchTab('findings')" class="px-3 py-2 text-sm font-medium border-b-2 border-transparent text-gray-500 hover:text-gray-700 focus:outline-none">
          All Findings (<span id="total-findings-badge">0</span>)
        </button>
        <button id="btn-tab-trends" onclick="switchTab('trends')" class="px-3 py-2 text-sm font-medium border-b-2 border-transparent text-gray-500 hover:text-gray-700 focus:outline-none">
          History & Trends
        </button>
      </div>

      <!-- Health Score Overview -->
      <div class="flex items-center space-x-4 bg-slate-50 px-3 py-1.5 rounded-lg border border-slate-200">
        <span class="text-xs font-semibold uppercase text-slate-500 tracking-wider">Project Health:</span>
        <div class="flex items-center space-x-2">
          <div class="w-24 bg-gray-200 rounded-full h-2.5 overflow-hidden">
            <div id="project-health-bar" class="h-full bg-emerald-500 rounded-full" style="width: 0%"></div>
          </div>
          <span id="project-health-score" class="text-sm font-extrabold text-slate-800">0.0%</span>
        </div>
      </div>
    </div>

    <!-- Tab Panels -->
    <div class="flex-1 min-h-0 relative">
      
      <!-- Panel 1: Lineage Graph -->
      <div id="panel-lineage" class="absolute inset-0 flex flex-col md:flex-row min-h-0">
        <!-- Sidebar controls & details -->
        <div class="w-full md:w-96 bg-white border-r border-gray-200 flex flex-col min-h-0 shrink-0">
          
          <!-- Search & Filters -->
          <div class="p-4 border-b border-gray-100 space-y-3 shrink-0">
            <div>
              <label for="search-input" class="block text-xs font-bold text-slate-500 uppercase tracking-wider mb-1">Search Models</label>
              <div class="relative">
                <input type="text" id="search-input" oninput="handleSearch(this.value)" placeholder="Search by model name..." class="w-full text-sm border border-gray-300 rounded-lg px-3 py-2 focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 outline-none">
                <!-- Dropdown suggestions -->
                <div id="search-suggestions" class="absolute left-0 right-0 mt-1 max-h-48 overflow-y-auto bg-white border border-gray-200 rounded-md shadow-lg z-50 hidden"></div>
              </div>
            </div>
            
            <div class="grid grid-cols-2 gap-2">
              <div>
                <label for="filter-owner" class="block text-[10px] font-bold text-slate-500 uppercase tracking-wider mb-0.5">Owner</label>
                <select id="filter-owner" onchange="applyFilters()" class="w-full text-xs border border-gray-300 rounded px-2 py-1 outline-none focus:ring-1 focus:ring-indigo-500">
                  <option value="all">All Owners</option>
                </select>
              </div>
              <div>
                <label for="filter-mat" class="block text-[10px] font-bold text-slate-500 uppercase tracking-wider mb-0.5">Materialization</label>
                <select id="filter-mat" onchange="applyFilters()" class="w-full text-xs border border-gray-300 rounded px-2 py-1 outline-none focus:ring-1 focus:ring-indigo-500">
                  <option value="all">All Types</option>
                </select>
              </div>
            </div>

            <div>
              <label class="block text-[10px] font-bold text-slate-500 uppercase tracking-wider mb-1">Status Filter</label>
              <div class="flex flex-wrap gap-1">
                <label class="flex items-center bg-slate-100 hover:bg-slate-200 text-slate-700 text-[10px] font-semibold px-2 py-1 rounded cursor-pointer border border-transparent">
                  <input type="radio" name="filter-status" value="all" checked onclick="applyFilters()" class="hidden">
                  <span>All</span>
                </label>
                <label class="flex items-center bg-red-50 hover:bg-red-100 text-red-700 text-[10px] font-semibold px-2 py-1 rounded cursor-pointer border border-transparent">
                  <input type="radio" name="filter-status" value="errors" onclick="applyFilters()" class="hidden">
                  <span>Errors</span>
                </label>
                <label class="flex items-center bg-amber-50 hover:bg-amber-100 text-amber-700 text-[10px] font-semibold px-2 py-1 rounded cursor-pointer border border-transparent">
                  <input type="radio" name="filter-status" value="warnings" onclick="applyFilters()" class="hidden">
                  <span>Warnings</span>
                </label>
                <label class="flex items-center bg-emerald-50 hover:bg-emerald-100 text-emerald-700 text-[10px] font-semibold px-2 py-1 rounded cursor-pointer border border-transparent">
                  <input type="radio" name="filter-status" value="passing" onclick="applyFilters()" class="hidden">
                  <span>Passing</span>
                </label>
              </div>
            </div>
          </div>

          <!-- Dynamic details pane -->
          <div class="flex-1 overflow-y-auto p-4" id="details-container">
            <!-- Default placeholder content -->
            <div id="details-placeholder" class="h-full flex flex-col items-center justify-center text-center text-slate-400 p-6">
              <svg class="w-12 h-12 mb-3 stroke-slate-300 fill-none" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M15 15l-2 5L9 9l11 4-5 2zm0 0l5 5M7.188 2.239l.777 2.897M5.136 7.965l-2.898-.777M13.95 4.05l-2.122 2.122m-5.657 5.656l-2.12 2.122"/>
              </svg>
              <h3 class="text-sm font-bold text-slate-600 mb-1">No Model Selected</h3>
              <p class="text-xs">Click a node on the lineage graph to inspect metadata, upstream dependencies, and specific lint rule findings.</p>
            </div>

            <!-- Model details content (initially hidden) -->
            <div id="details-content" class="hidden space-y-4">
              <div class="flex justify-between items-start">
                <div>
                  <h2 id="detail-name" class="text-base font-extrabold text-slate-800 break-all">...</h2>
                  <p id="detail-path" class="text-[10px] font-mono text-slate-400 break-all select-all mt-1">...</p>
                </div>
                <span id="detail-status" class="shrink-0 text-[10px] font-extrabold uppercase px-2 py-1 rounded tracking-wider">...</span>
              </div>

              <!-- Metadata Pills -->
              <div class="grid grid-cols-2 gap-2 text-xs border-t border-b border-gray-100 py-3">
                <div>
                  <span class="text-slate-400 block text-[10px] uppercase font-bold tracking-wider">Materialization</span>
                  <span id="detail-materialized" class="font-semibold text-slate-700 capitalize">...</span>
                </div>
                <div>
                  <span class="text-slate-400 block text-[10px] uppercase font-bold tracking-wider">Owner</span>
                  <span id="detail-owner" class="font-semibold text-slate-700">...</span>
                </div>
              </div>

              <!-- Description -->
              <div>
                <span class="text-slate-400 block text-[10px] uppercase font-bold tracking-wider mb-1">Description</span>
                <p id="detail-description" class="text-xs text-slate-600 leading-relaxed italic bg-slate-50 p-2.5 rounded border border-slate-100">...</p>
              </div>

              <!-- Grains -->
              <div id="detail-grains-container" class="hidden">
                <span class="text-slate-400 block text-[10px] uppercase font-bold tracking-wider mb-1">Unique Grains</span>
                <div id="detail-grains" class="flex flex-wrap gap-1"></div>
              </div>

              <!-- Lineage connections -->
              <div class="grid grid-cols-2 gap-2">
                <div>
                  <span class="text-slate-400 block text-[10px] uppercase font-bold tracking-wider mb-1.5">Upstream (Parents)</span>
                  <div id="detail-upstream" class="space-y-1 max-h-36 overflow-y-auto pr-1"></div>
                </div>
                <div>
                  <span class="text-slate-400 block text-[10px] uppercase font-bold tracking-wider mb-1.5">Downstream (Children)</span>
                  <div id="detail-downstream" class="space-y-1 max-h-36 overflow-y-auto pr-1"></div>
                </div>
              </div>

              <!-- Findings Box -->
              <div class="border-t border-gray-100 pt-3">
                <span id="detail-findings-header" class="text-slate-400 block text-[10px] uppercase font-bold tracking-wider mb-2">Findings</span>
                <div id="detail-findings-list" class="space-y-2"></div>
              </div>
            </div>

          </div>
        </div>

        <!-- Graph canvas -->
        <div class="flex-1 bg-white relative min-h-0">
          <div id="lineage-network"></div>
          
          <!-- Floating Controls -->
          <div class="absolute bottom-4 left-4 z-40 bg-white/90 backdrop-blur border border-gray-200 rounded-lg shadow px-3 py-2 flex items-center space-x-3 text-xs">
            <button onclick="zoomToFit()" class="font-semibold text-slate-700 hover:text-indigo-600 focus:outline-none flex items-center space-x-1">
              <svg class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 8V4m0 0h4M4 4l5 5m11-1V4m0 0h-4m4 0l-5 5M4 16v4m0 0h4m-4 0l5-5m11 5l-5-5m5 5v-4m0 4h-4"/></svg>
              <span>Fit Screen</span>
            </button>
            <div class="h-4 w-[1px] bg-gray-300"></div>
            <button id="btn-toggle-layout" onclick="toggleLayout()" class="font-semibold text-slate-700 hover:text-indigo-600 focus:outline-none flex items-center space-x-1">
              <svg class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 11H5m14 0a2 2 0 012 2v6a2 2 0 01-2 2H5a2 2 0 01-2-2v-6a2 2 0 012-2m14 0V9a2 2 0 00-2-2M5 11V9a2 2 0 012-2m0 0V5a2 2 0 012-2h6a2 2 0 012 2v2M7 7h10"/></svg>
              <span id="txt-layout-mode">Hierarchical (LR)</span>
            </button>
          </div>
        </div>
      </div>

      <!-- Panel 2: All Findings -->
      <div id="panel-findings" class="absolute inset-0 overflow-y-auto p-6 hidden">
        <div class="max-w-7xl mx-auto space-y-6">
          <div class="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-4">
            <div>
              <h2 class="text-xl font-extrabold text-slate-800">Lint rule violations and findings</h2>
              <p class="text-sm text-slate-500 mt-1">Review all detected architectural and code format issues across the transformation pipeline.</p>
            </div>
            
            <div class="flex items-center space-x-2 w-full sm:w-auto">
              <input type="text" id="finding-search" oninput="filterFindingsTable()" placeholder="Filter findings..." class="text-sm border border-gray-300 rounded-lg px-3 py-1.5 focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 outline-none w-full sm:w-64">
              <select id="finding-severity-filter" onchange="filterFindingsTable()" class="text-sm border border-gray-300 rounded-lg px-3 py-1.5 outline-none focus:ring-2 focus:ring-indigo-500">
                <option value="all">All Severities</option>
                <option value="error">Errors</option>
                <option value="warning">Warnings</option>
              </select>
            </div>
          </div>

          <!-- Project Level Findings (Global Checks) -->
          <div id="project-findings-section" class="hidden">
            <h3 class="text-sm font-bold text-slate-700 uppercase tracking-wider mb-3">Project-Level Findings</h3>
            <div id="project-findings-list" class="grid grid-cols-1 md:grid-cols-2 gap-3 mb-6"></div>
          </div>

          <!-- Detailed Findings Table -->
          <div class="bg-white border border-gray-200 rounded-xl overflow-hidden shadow-sm">
            <div class="overflow-x-auto">
              <table class="min-w-full divide-y divide-gray-200 text-left text-sm" id="findings-table">
                <thead class="bg-slate-50 text-slate-700 font-bold uppercase tracking-wider text-xs">
                  <tr>
                    <th scope="col" class="px-6 py-3 w-32">Severity</th>
                    <th scope="col" class="px-6 py-3">Model</th>
                    <th scope="col" class="px-6 py-3">Rule/Check</th>
                    <th scope="col" class="px-6 py-3">Violation Details</th>
                  </tr>
                </thead>
                <tbody class="divide-y divide-gray-200 text-slate-700" id="findings-table-body">
                  <!-- JS generated rows -->
                </tbody>
              </table>
              <div id="no-findings-alert" class="hidden p-8 text-center text-slate-400">
                No findings match the current criteria.
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- Panel 3: History & Trends -->
      <div id="panel-trends" class="absolute inset-0 overflow-y-auto p-6 hidden">
        <div class="max-w-7xl mx-auto space-y-8">
          
          <!-- Charts row -->
          <div class="grid grid-cols-1 lg:grid-cols-2 gap-6">
            <div class="bg-white p-5 rounded-xl border border-gray-200 shadow-sm">
              <h3 class="text-sm font-bold text-slate-700 uppercase tracking-wider mb-4">Overall Project Health Score Trend</h3>
              <div class="h-64 relative">
                <canvas id="chart-health"></canvas>
              </div>
            </div>
            <div class="bg-white p-5 rounded-xl border border-gray-200 shadow-sm">
              <h3 class="text-sm font-bold text-slate-700 uppercase tracking-wider mb-4">Violations Trend (Errors & Warnings)</h3>
              <div class="h-64 relative">
                <canvas id="chart-violations"></canvas>
              </div>
            </div>
          </div>

          <!-- History Table -->
          <div>
            <h3 class="text-sm font-bold text-slate-700 uppercase tracking-wider mb-3">Historical Executions</h3>
            <div class="bg-white border border-gray-200 rounded-xl overflow-hidden shadow-sm">
              <table class="min-w-full divide-y divide-gray-200 text-left text-sm">
                <thead class="bg-slate-50 text-slate-700 font-bold uppercase tracking-wider text-xs">
                  <tr>
                    <th scope="col" class="px-6 py-3">Execution Date</th>
                    <th scope="col" class="px-6 py-3 text-right">Health Score</th>
                    <th scope="col" class="px-6 py-3 text-right">Errors</th>
                    <th scope="col" class="px-6 py-3 text-right">Warnings</th>
                  </tr>
                </thead>
                <tbody class="divide-y divide-gray-200 text-slate-700" id="history-table-body">
                  <!-- JS generated rows -->
                </tbody>
              </table>
            </div>
          </div>
          
        </div>
      </div>

    </div>
  </main>

  <script>
    // Embedded JSON from compiler
    <!-- INSERT_TFF_DATA_HERE -->

    // Global state
    let activeTab = 'lineage';
    let network = null;
    let nodesDataset = null;
    let edgesDataset = null;
    let nodesView = null;
    let edgesView = null;
    let isHierarchical = true;
    let currentSelectedNodeId = null;

    // Run on startup
    window.addEventListener('DOMContentLoaded', () => {
      initDashboard();
      initLineageGraph();
      initFindingsTable();
      initTrendsAndHistory();
    });

    function initDashboard() {
      // Set timestamp & provider
      document.getElementById('generation-timestamp').textContent = new Date(TFF_DATA.generated_at).toLocaleString();
      document.getElementById('provider-badge').textContent = TFF_DATA.provider;

      // Set health score metrics
      const score = TFF_DATA.overall_score;
      document.getElementById('project-health-score').textContent = score.toFixed(1) + '%';
      
      const healthBar = document.getElementById('project-health-bar');
      healthBar.style.width = score + '%';
      
      // Color bar based on score thresholds
      if (score >= 90) {
        healthBar.className = 'h-full bg-emerald-500 rounded-full';
      } else if (score >= 70) {
        healthBar.className = 'h-full bg-amber-500 rounded-full';
      } else {
        healthBar.className = 'h-full bg-rose-500 rounded-full';
      }

      // Count total findings
      let count = TFF_DATA.project_findings.length;
      Object.values(TFF_DATA.models).forEach(model => {
        count += model.findings.length;
      });
      document.getElementById('total-findings-badge').textContent = count;

      // Populate filters dropdowns
      const owners = new Set();
      const mats = new Set();
      Object.values(TFF_DATA.models).forEach(model => {
        if (model.owner) owners.add(model.owner);
        if (model.materialized) mats.add(model.materialized);
      });

      const ownerSelect = document.getElementById('filter-owner');
      Array.from(owners).sort().forEach(owner => {
        const opt = document.createElement('option');
        opt.value = owner;
        opt.textContent = owner;
        ownerSelect.appendChild(opt);
      });

      const matSelect = document.getElementById('filter-mat');
      Array.from(mats).sort().forEach(mat => {
        const opt = document.createElement('option');
        opt.value = mat;
        opt.textContent = mat;
        matSelect.appendChild(opt);
      });
    }

    function switchTab(tabName) {
      activeTab = tabName;
      
      // Toggle tabs UI
      const tabs = ['lineage', 'findings', 'trends'];
      tabs.forEach(t => {
        const btn = document.getElementById(`btn-tab-${t}`);
        const panel = document.getElementById(`panel-${t}`);
        if (t === tabName) {
          btn.className = "px-3 py-2 text-sm font-semibold border-b-2 border-indigo-600 text-indigo-600 focus:outline-none";
          panel.classList.remove('hidden');
        } else {
          btn.className = "px-3 py-2 text-sm font-medium border-b-2 border-transparent text-gray-500 hover:text-gray-700 focus:outline-none";
          panel.classList.add('hidden');
        }
      });

      // Special handling on layout recalculation
      if (tabName === 'lineage' && network) {
        network.fit();
      }
    }

    // Node Visual Properties Mapper
    function getNodeVisProperties(model) {
      let color, border, fontColor;
      
      if (model.is_external) {
        color = '#f1f5f9'; // slate-100
        border = '#cbd5e1'; // slate-300
        fontColor = '#475569'; // slate-600
      } else if (model.status === 'error') {
        color = '#fee2e2'; // red-100
        border = '#f87171'; // red-400
        fontColor = '#991b1b'; // red-800
      } else if (model.status === 'warning') {
        color = '#fef3c7'; // amber-100
        border = '#fbbf24'; // amber-400
        fontColor = '#92400e'; // amber-800
      } else {
        color = '#d1fae5'; // emerald-100
        border = '#34d399'; // emerald-400
        fontColor = '#065f46'; // emerald-800
      }
      
      return {
        id: model.id,
        label: model.name,
        shape: 'box',
        margin: { top: 8, bottom: 8, left: 14, right: 14 },
        color: {
          background: color,
          border: border,
          highlight: { background: color, border: '#6366f1' }, // indigo-500
          hover: { background: color, border: '#818cf8' }
        },
        font: { 
          color: fontColor, 
          face: 'ui-sans-serif, system-ui, sans-serif',
          size: 13,
          bold: { color: fontColor, size: 13 }
        },
        borderWidth: 2,
        borderWidthSelected: 3,
        shapeProperties: {
          borderDashed: model.is_symbolic
        },
        title: `<b>${model.name}</b><br/>Materialized: ${model.materialized || 'unknown'}`
      };
    }

    function initLineageGraph() {
      nodesDataset = new vis.DataSet();
      edgesDataset = new vis.DataSet();

      const allModelIds = new Set(Object.keys(TFF_DATA.models));

      // 1. Populate node dataset
      Object.values(TFF_DATA.models).forEach(model => {
        nodesDataset.add(getNodeVisProperties(model));
      });

      // 2. Populate edge dataset & virtual node resolution
      Object.values(TFF_DATA.models).forEach(model => {
        (model.depends_on || []).forEach(depId => {
          // If the dependency does not exist in nodes dataset, register it dynamically as source
          if (!nodesDataset.get(depId)) {
            // Split name and display basename
            const displayName = depId.split('.').pop();
            nodesDataset.add({
              id: depId,
              label: displayName,
              shape: 'box',
              margin: { top: 8, bottom: 8, left: 14, right: 14 },
              color: {
                background: '#f8fafc', // slate-50
                border: '#cbd5e1'
              },
              font: { color: '#64748b', face: 'ui-sans-serif, system-ui, sans-serif' },
              borderWidth: 2,
              shapeProperties: { borderDashed: true }
            });
          }
          edgesDataset.add({ from: depId, to: model.id });
        });
      });

      // 3. Create views for filtering
      nodesView = new vis.DataView(nodesDataset, {
        filter: function(node) {
          const model = TFF_DATA.models[node.id];
          if (!model) return true; // keep external/sources virtual nodes

          // Status Filter
          const statusVal = document.querySelector('input[name="filter-status"]:checked').value;
          if (statusVal !== 'all') {
            if (statusVal === 'errors' && model.status !== 'error') return false;
            if (statusVal === 'warnings' && model.status !== 'warning') return false;
            if (statusVal === 'passing' && model.status !== 'pass') return false;
          }

          // Owner Filter
          const ownerVal = document.getElementById('filter-owner').value;
          if (ownerVal !== 'all' && model.owner !== ownerVal) return false;

          // Materialization Filter
          const matVal = document.getElementById('filter-mat').value;
          if (matVal !== 'all' && model.materialized !== matVal) return false;

          return true;
        }
      });

      edgesView = new vis.DataView(edgesDataset, {
        filter: function(edge) {
          return nodesView.get(edge.from) && nodesView.get(edge.to);
        }
      });

      // 4. Initialize network options
      const container = document.getElementById('lineage-network');
      const networkData = { nodes: nodesView, edges: edgesView };
      
      const networkOptions = {
        nodes: {
          shadow: { enabled: true, color: 'rgba(0,0,0,0.05)', size: 4, x: 1, y: 1 }
        },
        edges: {
          arrows: { to: { enabled: true, scaleFactor: 0.6 } },
          color: { color: '#cbd5e1', highlight: '#6366f1', hover: '#94a3b8' },
          smooth: { type: 'cubicBezier', forceDirection: 'horizontal', roundness: 0.4 }
        },
        layout: {
          hierarchical: {
            enabled: true,
            direction: 'LR',
            sortMethod: 'directed',
            nodeSpacing: 140,
            treeSpacing: 180,
            levelCalculationMethod: 'hubsize'
          }
        },
        interaction: {
          hover: true,
          navigationButtons: false,
          keyboard: false
        },
        physics: {
          enabled: false
        }
      };

      network = new vis.Network(container, networkData, networkOptions);

      // Event handlers
      network.on("click", function(params) {
        if (params.nodes.length > 0) {
          selectNode(params.nodes[0]);
        } else {
          clearSelection();
        }
      });
    }

    function toggleLayout() {
      isHierarchical = !isHierarchical;
      const modeBtn = document.getElementById('txt-layout-mode');
      
      if (isHierarchical) {
        modeBtn.textContent = 'Hierarchical (LR)';
        network.setOptions({
          layout: { hierarchical: { enabled: true, direction: 'LR', sortMethod: 'directed', nodeSpacing: 140 } },
          physics: { enabled: false }
        });
      } else {
        modeBtn.textContent = 'Free Physics';
        network.setOptions({
          layout: { hierarchical: { enabled: false } },
          physics: { enabled: true, solver: 'forceAtlas2Based', forceAtlas2Based: { gravitationalConstant: -50, centralGravity: 0.01, springLength: 100, springConstant: 0.08, damping: 0.4 } }
        });
      }
    }

    function applyFilters() {
      if (nodesView) nodesView.refresh();
      if (edgesView) edgesView.refresh();
      clearSelection();
    }

    function selectNode(nodeId) {
      currentSelectedNodeId = nodeId;
      const model = TFF_DATA.models[nodeId];

      if (!model) {
        // Virtual/external node details
        document.getElementById('details-placeholder').classList.add('hidden');
        const content = document.getElementById('details-content');
        content.classList.remove('hidden');

        document.getElementById('detail-name').textContent = nodeId.split('.').pop();
        document.getElementById('detail-path').textContent = nodeId;
        
        const statusBadge = document.getElementById('detail-status');
        statusBadge.textContent = 'External';
        statusBadge.className = 'shrink-0 text-[10px] font-extrabold uppercase px-2 py-1 rounded tracking-wider bg-slate-100 text-slate-600';
        
        document.getElementById('detail-materialized').textContent = 'External Source';
        document.getElementById('detail-owner').textContent = 'N/A';
        document.getElementById('detail-description').textContent = 'This is an external source or seed not directly checked by TFF rules.';
        document.getElementById('detail-grains-container').classList.add('hidden');
        document.getElementById('detail-upstream').innerHTML = '<span class="text-xs text-slate-400">None</span>';
        
        // Calculate children
        const children = [];
        edgesDataset.forEach(edge => {
          if (edge.from === nodeId) children.push(edge.to);
        });
        
        const downContainer = document.getElementById('detail-downstream');
        downContainer.innerHTML = '';
        if (children.length > 0) {
          children.forEach(childId => {
            const childModel = TFF_DATA.models[childId];
            const childName = childModel ? childModel.name : childId.split('.').pop();
            const childStatus = childModel ? childModel.status : 'pass';
            const colorClass = getBadgeColorClass(childStatus);
            
            const btn = document.createElement('button');
            btn.className = `w-full text-left text-xs font-semibold px-2 py-1 rounded border truncate hover:shadow-sm ${colorClass}`;
            btn.onclick = () => focusAndSelectNode(childId);
            btn.textContent = childName;
            downContainer.appendChild(btn);
          });
        } else {
          downContainer.innerHTML = '<span class="text-xs text-slate-400">None</span>';
        }
        
        document.getElementById('detail-findings-header').classList.add('hidden');
        document.getElementById('detail-findings-list').innerHTML = '';
        return;
      }

      // Hide placeholder
      document.getElementById('details-placeholder').classList.add('hidden');
      const content = document.getElementById('details-content');
      content.classList.remove('hidden');

      // Populate Name, Path, Materialization, Owner, Description
      document.getElementById('detail-name').textContent = model.name;
      document.getElementById('detail-path').textContent = model.path || 'N/A';
      document.getElementById('detail-materialized').textContent = model.materialized || 'N/A';
      document.getElementById('detail-owner').textContent = model.owner || 'Unassigned';
      
      const descEl = document.getElementById('detail-description');
      if (model.description) {
        descEl.textContent = model.description;
        descEl.className = 'text-xs text-slate-600 leading-relaxed italic bg-slate-50 p-2.5 rounded border border-slate-100';
      } else {
        descEl.textContent = 'No description provided for this model.';
        descEl.className = 'text-xs text-slate-400 leading-relaxed italic bg-slate-50 p-2.5 rounded border border-slate-100';
      }

      // Status Badge
      const statusBadge = document.getElementById('detail-status');
      statusBadge.textContent = model.status;
      if (model.status === 'error') {
        statusBadge.className = 'shrink-0 text-[10px] font-extrabold uppercase px-2 py-1 rounded tracking-wider bg-rose-100 text-rose-800 border border-rose-200';
      } else if (model.status === 'warning') {
        statusBadge.className = 'shrink-0 text-[10px] font-extrabold uppercase px-2 py-1 rounded tracking-wider bg-amber-100 text-amber-800 border border-amber-200';
      } else {
        statusBadge.className = 'shrink-0 text-[10px] font-extrabold uppercase px-2 py-1 rounded tracking-wider bg-emerald-100 text-emerald-800 border border-emerald-200';
      }

      // Grains
      const grainsContainer = document.getElementById('detail-grains-container');
      const grainsEl = document.getElementById('detail-grains');
      grainsEl.innerHTML = '';
      if (model.grains && model.grains.length > 0) {
        grainsContainer.classList.remove('hidden');
        model.grains.forEach(g => {
          const badge = document.createElement('span');
          badge.className = 'bg-indigo-50 text-indigo-700 text-[10px] font-bold px-2 py-0.5 rounded border border-indigo-100';
          badge.textContent = g;
          grainsEl.appendChild(badge);
        });
      } else {
        grainsContainer.classList.add('hidden');
      }

      // Parents/Upstream
      const upEl = document.getElementById('detail-upstream');
      upEl.innerHTML = '';
      if (model.depends_on && model.depends_on.length > 0) {
        model.depends_on.forEach(pId => {
          const parentModel = TFF_DATA.models[pId];
          const parentName = parentModel ? parentModel.name : pId.split('.').pop();
          const parentStatus = parentModel ? parentModel.status : 'pass';
          const colorClass = getBadgeColorClass(parentStatus);

          const btn = document.createElement('button');
          btn.className = `w-full text-left text-xs font-semibold px-2 py-1 rounded border truncate hover:shadow-sm ${colorClass}`;
          btn.onclick = () => focusAndSelectNode(pId);
          btn.textContent = parentName;
          upEl.appendChild(btn);
        });
      } else {
        upEl.innerHTML = '<span class="text-xs text-slate-400">None</span>';
      }

      // Children/Downstream
      const downEl = document.getElementById('detail-downstream');
      downEl.innerHTML = '';
      const children = [];
      edgesDataset.forEach(edge => {
        if (edge.from === nodeId) children.push(edge.to);
      });

      if (children.length > 0) {
        children.forEach(cId => {
          const childModel = TFF_DATA.models[cId];
          const childName = childModel ? childModel.name : cId.split('.').pop();
          const childStatus = childModel ? childModel.status : 'pass';
          const colorClass = getBadgeColorClass(childStatus);

          const btn = document.createElement('button');
          btn.className = `w-full text-left text-xs font-semibold px-2 py-1 rounded border truncate hover:shadow-sm ${colorClass}`;
          btn.onclick = () => focusAndSelectNode(cId);
          btn.textContent = childName;
          downEl.appendChild(btn);
        });
      } else {
        downEl.innerHTML = '<span class="text-xs text-slate-400">None</span>';
      }

      // Findings List
      document.getElementById('detail-findings-header').classList.remove('hidden');
      const findingsList = document.getElementById('detail-findings-list');
      findingsList.innerHTML = '';
      if (model.findings && model.findings.length > 0) {
        model.findings.forEach(f => {
          const box = document.createElement('div');
          const isErr = f.severity === 'error';
          box.className = `p-2.5 rounded text-xs leading-relaxed border ${
            isErr ? 'bg-rose-50 text-rose-800 border-rose-100' : 'bg-amber-50 text-amber-800 border-amber-100'
          }`;
          
          const label = document.createElement('div');
          label.className = `font-extrabold uppercase tracking-wider text-[9px] mb-0.5 opacity-80`;
          label.textContent = f.check;
          box.appendChild(label);
          
          const msg = document.createElement('div');
          msg.textContent = f.message;
          box.appendChild(msg);
          
          findingsList.appendChild(box);
        });
      } else {
        const box = document.createElement('div');
        box.className = 'p-3 rounded text-xs bg-emerald-50 text-emerald-800 border border-emerald-100 font-semibold flex items-center space-x-1.5';
        box.innerHTML = `<svg class="w-4 h-4 shrink-0 stroke-emerald-600" fill="none" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2.5" d="M5 13l4 4L19 7"/></svg><span>No fitness violations found</span>`;
        findingsList.appendChild(box);
      }
    }

    function getBadgeColorClass(status) {
      if (status === 'error') return 'bg-rose-50 text-rose-700 border-rose-200 hover:bg-rose-100';
      if (status === 'warning') return 'bg-amber-50 text-amber-700 border-amber-200 hover:bg-amber-100';
      return 'bg-emerald-50 text-emerald-700 border-emerald-200 hover:bg-emerald-100';
    }

    function focusAndSelectNode(nodeId) {
      network.selectNodes([nodeId]);
      network.focus(nodeId, {
        scale: 1.1,
        animation: { duration: 600, easingFunction: 'easeInOutQuad' }
      });
      selectNode(nodeId);
    }

    function clearSelection() {
      currentSelectedNodeId = null;
      document.getElementById('details-placeholder').classList.remove('hidden');
      document.getElementById('details-content').classList.add('hidden');
    }

    function zoomToFit() {
      if (network) network.fit({ animation: { duration: 600 } });
    }

    // Auto-complete suggestion search
    function handleSearch(query) {
      const suggestDiv = document.getElementById('search-suggestions');
      if (!query.trim()) {
        suggestDiv.innerHTML = '';
        suggestDiv.classList.add('hidden');
        return;
      }

      const q = query.toLowerCase();
      // Match models which are currently visible in the nodes dataset view
      const matches = [];
      nodesView.forEach(node => {
        if (node.label.toLowerCase().includes(q)) {
          matches.push({ id: node.id, name: node.label });
        }
      });

      if (matches.length === 0) {
        suggestDiv.innerHTML = '<div class="p-2 text-xs text-slate-400 italic">No models found</div>';
        suggestDiv.classList.remove('hidden');
        return;
      }

      suggestDiv.innerHTML = '';
      matches.slice(0, 10).forEach(match => {
        const item = document.createElement('div');
        item.className = 'p-2 text-xs text-slate-700 hover:bg-slate-50 cursor-pointer font-medium border-b border-slate-50';
        item.textContent = match.name;
        item.onclick = () => {
          document.getElementById('search-input').value = match.name;
          suggestDiv.classList.add('hidden');
          focusAndSelectNode(match.id);
        };
        suggestDiv.appendChild(item);
      });
      suggestDiv.classList.remove('hidden');
    }

    // Hide search suggestions on document click
    document.addEventListener('click', (e) => {
      const suggestDiv = document.getElementById('search-suggestions');
      const searchInput = document.getElementById('search-input');
      if (suggestDiv && e.target !== searchInput) {
        suggestDiv.classList.add('hidden');
      }
    });

    /* Tab 2: Findings Table initialization & filtering */
    function initFindingsTable() {
      // Build project-wide findings if any
      const projContainer = document.getElementById('project-findings-list');
      const projSection = document.getElementById('project-findings-section');
      
      if (TFF_DATA.project_findings && TFF_DATA.project_findings.length > 0) {
        projSection.classList.remove('hidden');
        projContainer.innerHTML = '';
        TFF_DATA.project_findings.forEach(f => {
          const item = document.createElement('div');
          const isErr = f.severity === 'error';
          item.className = `p-3 rounded-lg border text-xs ${
            isErr ? 'bg-rose-50 text-rose-800 border-rose-100' : 'bg-amber-50 text-amber-800 border-amber-100'
          }`;
          item.innerHTML = `<div class="font-extrabold uppercase text-[9px] tracking-wider mb-0.5 opacity-80">${f.check}</div><div>${f.message}</div>`;
          projContainer.appendChild(item);
        });
      }

      // Build table rows
      const tbody = document.getElementById('findings-table-body');
      tbody.innerHTML = '';

      Object.values(TFF_DATA.models).forEach(model => {
        model.findings.forEach(f => {
          const tr = document.createElement('tr');
          tr.className = 'hover:bg-slate-50 transition-colors cursor-pointer border-b border-gray-100';
          tr.onclick = () => {
            // Switch to lineage and focus node
            switchTab('lineage');
            focusAndSelectNode(model.id);
          };

          // Severity Cell
          const isErr = f.severity === 'error';
          const sevClass = isErr ? 'bg-rose-100 text-rose-800' : 'bg-amber-100 text-amber-800';
          const sevCell = `<td class="px-6 py-4 whitespace-nowrap"><span class="text-[10px] font-extrabold uppercase px-2 py-0.5 rounded tracking-wider ${sevClass}">${f.severity}</span></td>`;
          
          // Model Name Cell
          const modelCell = `<td class="px-6 py-4 font-bold text-slate-800">${model.name}</td>`;
          
          // Check/Rule Name Cell
          const checkCell = `<td class="px-6 py-4 text-xs font-mono text-slate-500">${f.check}</td>`;
          
          // Detail message Cell
          const msgCell = `<td class="px-6 py-4 text-slate-600 break-words max-w-md">${f.message}</td>`;

          tr.innerHTML = sevCell + modelCell + checkCell + msgCell;
          // Store raw info for filtering
          tr.setAttribute('data-model', model.name.toLowerCase());
          tr.setAttribute('data-check', f.check.toLowerCase());
          tr.setAttribute('data-message', f.message.toLowerCase());
          tr.setAttribute('data-severity', f.severity);

          tbody.appendChild(tr);
        });
      });
      
      filterFindingsTable();
    }

    function filterFindingsTable() {
      const q = document.getElementById('finding-search').value.toLowerCase();
      const sev = document.getElementById('finding-severity-filter').value;
      const tbody = document.getElementById('findings-table-body');
      const rows = tbody.getElementsByTagName('tr');
      const alertDiv = document.getElementById('no-findings-alert');

      let visibleCount = 0;
      for (let i = 0; i < rows.length; i++) {
        const row = rows[i];
        const rowModel = row.getAttribute('data-model');
        const rowCheck = row.getAttribute('data-check');
        const rowMsg = row.getAttribute('data-message');
        const rowSev = row.getAttribute('data-severity');

        let matchesSearch = !q || rowModel.includes(q) || rowCheck.includes(q) || rowMsg.includes(q);
        let matchesSeverity = sev === 'all' || rowSev === sev;

        if (matchesSearch && matchesSeverity) {
          row.classList.remove('hidden');
          visibleCount++;
        } else {
          row.classList.add('hidden');
        }
      }

      if (visibleCount === 0 && rows.length > 0) {
        alertDiv.classList.remove('hidden');
      } else {
        alertDiv.classList.add('hidden');
      }
    }

    /* Tab 3: Trends Charts & Historical table */
    function initTrendsAndHistory() {
      const history = TFF_DATA.history;
      
      // Populate History Table
      const tbody = document.getElementById('history-table-body');
      tbody.innerHTML = '';
      
      // Reverse history so latest runs are at the top of the table
      const tableHistory = [...history].reverse();
      
      tableHistory.forEach(run => {
        const tr = document.createElement('tr');
        tr.className = 'border-b border-gray-100 hover:bg-slate-50';
        
        const dateCell = `<td class="px-6 py-3.5 font-semibold text-slate-800">${new Date(run.date).toLocaleDateString(undefined, {month: 'short', day: 'numeric', year: 'numeric'})}</td>`;
        
        let scoreText = '·';
        let scoreColor = 'text-slate-400';
        if (run.health_score !== null) {
          scoreText = run.health_score.toFixed(1) + '%';
          if (run.health_score >= 90) scoreColor = 'text-emerald-600 font-extrabold';
          else if (run.health_score >= 70) scoreColor = 'text-amber-600 font-extrabold';
          else scoreColor = 'text-rose-600 font-extrabold';
        }
        const scoreCell = `<td class="px-6 py-3.5 text-right ${scoreColor}">${scoreText}</td>`;
        
        const errVal = run.errors_count !== null ? run.errors_count : 0;
        const warnVal = run.warnings_count !== null ? run.warnings_count : 0;
        
        const errCell = `<td class="px-6 py-3.5 text-right font-medium ${errVal > 0 ? 'text-rose-600 font-bold' : 'text-slate-400'}">${errVal}</td>`;
        const warnCell = `<td class="px-6 py-3.5 text-right font-medium ${warnVal > 0 ? 'text-amber-600 font-bold' : 'text-slate-400'}">${warnVal}</td>`;

        tr.innerHTML = dateCell + scoreCell + errCell + warnCell;
        tbody.appendChild(tr);
      });

      // Filter history for charts (ignore entries missing scores/findings)
      const healthRuns = history.filter(h => h.health_score !== null);
      const lintRuns = history.filter(h => h.errors_count !== null || h.warnings_count !== null);

      if (healthRuns.length === 0) return;

      // 1. Health Score Trend Line Chart
      const ctxHealth = document.getElementById('chart-health').getContext('2d');
      new Chart(ctxHealth, {
        type: 'line',
        data: {
          labels: healthRuns.map(h => new Date(h.date).toLocaleDateString(undefined, {month: 'short', day: 'numeric'})),
          datasets: [{
            label: 'Health Score',
            data: healthRuns.map(h => h.health_score),
            borderColor: '#059669', // emerald-600
            backgroundColor: 'rgba(5, 150, 105, 0.05)',
            borderWidth: 2,
            tension: 0.1,
            fill: true,
            pointBackgroundColor: '#059669',
            pointRadius: 3
          }]
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          plugins: { legend: { display: false } },
          scales: {
            y: {
              min: 0,
              max: 100,
              ticks: { callback: val => val + '%' },
              grid: { color: '#f1f5f9' }
            },
            x: {
              grid: { display: false }
            }
          }
        }
      });

      // 2. Violations Trend Line Chart (Errors & Warnings)
      const ctxViolations = document.getElementById('chart-violations').getContext('2d');
      new Chart(ctxViolations, {
        type: 'line',
        data: {
          labels: lintRuns.map(h => new Date(h.date).toLocaleDateString(undefined, {month: 'short', day: 'numeric'})),
          datasets: [
            {
              label: 'Errors',
              data: lintRuns.map(h => h.errors_count || 0),
              borderColor: '#dc2626', // red-600
              backgroundColor: 'transparent',
              borderWidth: 2,
              tension: 0.1,
              pointBackgroundColor: '#dc2626',
              pointRadius: 3
            },
            {
              label: 'Warnings',
              data: lintRuns.map(h => h.warnings_count || 0),
              borderColor: '#d97706', // amber-600
              backgroundColor: 'transparent',
              borderWidth: 2,
              tension: 0.1,
              pointBackgroundColor: '#d97706',
              pointRadius: 3
            }
          ]
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          plugins: { legend: { position: 'top', labels: { boxWidth: 12, font: { size: 10 } } } },
          scales: {
            y: {
              beginAtZero: true,
              ticks: { precision: 0 },
              grid: { color: '#f1f5f9' }
            },
            x: {
              grid: { display: false }
            }
          }
        }
      });
    }
  </script>
</body>
</html>
"""
