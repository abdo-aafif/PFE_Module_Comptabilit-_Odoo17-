/** @odoo-module **/
/*
 * Dashboard OWL — États Financiers (Bilan / CPC / Flux)
 * Affiche 4 KPI cards + 4 graphiques Chart.js interactifs.
 * Backend : financial.statement.wizard.get_dashboard_data()
 */

import { Component, useState, useRef, onMounted, onWillStart, onWillUnmount } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { loadJS } from "@web/core/assets";

export class ComptaDashboard extends Component {
    static template = "pfe.ComptaDashboard";

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.notification = useService("notification");

        // Refs pour les 4 canvases Chart.js
        this.actifCanvas = useRef("actifCanvas");
        this.passifCanvas = useRef("passifCanvas");
        this.cpcCanvas = useRef("cpcCanvas");
        this.fluxCanvas = useRef("fluxCanvas");

        // Instances Chart.js (pour pouvoir les détruire au refresh)
        this.charts = {};

        const today = new Date();
        this.state = useState({
            loading: true,
            dateFrom: `${today.getFullYear()}-01-01`,
            dateTo: `${today.getFullYear()}-12-31`,
            companyName: "",
            currency: "MAD",
            kpis: {
                total_actif: 0,
                total_passif: 0,
                resultat_net: 0,
                tresorerie_nette: 0,
            },
        });

        onWillStart(async () => {
            // Chart.js est déjà bundlé dans web.assets_backend d'Odoo 17
            await loadJS("/web/static/lib/Chart/Chart.js");
        });

        onMounted(() => this.loadData());

        onWillUnmount(() => this.destroyCharts());
    }

    // ─── Data loading ─────────────────────────────────────────────
    async loadData() {
        this.state.loading = true;
        let data;
        try {
            data = await this.orm.call(
                "financial.statement.wizard",
                "get_dashboard_data",
                [],
                {
                    date_from: this.state.dateFrom,
                    date_to: this.state.dateTo,
                },
            );
            this.state.companyName = data.company_name;
            this.state.currency = data.currency;
            Object.assign(this.state.kpis, data.kpis);
        } catch (err) {
            this.notification.add("Erreur lors du chargement des données.", { type: "danger" });
            console.error("[ComptaDashboard] loadData failed:", err);
            this.state.loading = false;
            return;
        }
        this.state.loading = false;

        // Attendre que OWL ait patché le DOM (le t-else est conditionnel
        // mais désormais on garde les canvas toujours rendus — robuste quand même).
        await new Promise((resolve) => requestAnimationFrame(resolve));
        await new Promise((resolve) => requestAnimationFrame(resolve));
        try {
            this.renderCharts(data);
        } catch (err) {
            console.error("[ComptaDashboard] renderCharts failed:", err);
            this.notification.add("Erreur lors du rendu des graphiques.", { type: "warning" });
        }
    }

    // ─── Chart rendering ──────────────────────────────────────────
    destroyCharts() {
        Object.values(this.charts).forEach((c) => c && c.destroy());
        this.charts = {};
    }

    renderCharts(data) {
        this.destroyCharts();

        // Garde-fou : si Chart.js n'est pas dispo, on arrête proprement
        const ChartLib = window.Chart;
        if (!ChartLib) {
            console.error("[ComptaDashboard] Chart.js non chargé (window.Chart absent).");
            return;
        }

        // 1. Donut — Structure de l'Actif
        if (this.actifCanvas.el) {
            this.charts.actif = new ChartLib(this.actifCanvas.el, {
                type: "doughnut",
                data: {
                    labels: data.actif_chart.labels,
                    datasets: [{
                        data: data.actif_chart.data,
                        backgroundColor: ["#4e79a7", "#59a14f", "#f28e2b"],
                        borderWidth: 2,
                    }],
                },
                options: this.donutOptions("Structure de l'Actif"),
            });
        }

        // 2. Donut — Structure du Passif
        if (this.passifCanvas.el) {
            this.charts.passif = new ChartLib(this.passifCanvas.el, {
                type: "doughnut",
                data: {
                    labels: data.passif_chart.labels,
                    datasets: [{
                        data: data.passif_chart.data,
                        backgroundColor: ["#e15759", "#76b7b2", "#edc949"],
                        borderWidth: 2,
                    }],
                },
                options: this.donutOptions("Structure du Passif"),
            });
        }

        // 3. Bar — CPC
        if (this.cpcCanvas.el) {
            this.charts.cpc = new ChartLib(this.cpcCanvas.el, {
                type: "bar",
                data: {
                    labels: data.cpc_chart.labels,
                    datasets: [{
                        label: `Montant (${data.currency})`,
                        data: data.cpc_chart.data,
                        backgroundColor: data.cpc_chart.data.map((v) =>
                            v >= 0 ? "#59a14f" : "#e15759"
                        ),
                        borderRadius: 6,
                    }],
                },
                options: this.barOptions("Compte de Produits et Charges"),
            });
        }

        // 4. Bar — Flux de Trésorerie
        if (this.fluxCanvas.el) {
            this.charts.flux = new ChartLib(this.fluxCanvas.el, {
                type: "bar",
                data: {
                    labels: data.flux_chart.labels,
                    datasets: [{
                        label: `Flux net (${data.currency})`,
                        data: data.flux_chart.data,
                        backgroundColor: data.flux_chart.data.map((v) =>
                            v >= 0 ? "#4e79a7" : "#e15759"
                        ),
                        borderRadius: 6,
                    }],
                },
                options: this.barOptions("Flux de Trésorerie"),
            });
        }
    }

    donutOptions(title) {
        return {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                title: { display: true, text: title, font: { size: 14, weight: "bold" } },
                legend: { position: "bottom" },
                tooltip: {
                    callbacks: {
                        label: (ctx) =>
                            `${ctx.label}: ${this.formatMoney(ctx.parsed)} ${this.state.currency}`,
                    },
                },
            },
        };
    }

    barOptions(title) {
        return {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                title: { display: true, text: title, font: { size: 14, weight: "bold" } },
                legend: { display: false },
                tooltip: {
                    callbacks: {
                        label: (ctx) =>
                            `${this.formatMoney(ctx.parsed.y)} ${this.state.currency}`,
                    },
                },
            },
            scales: {
                y: {
                    beginAtZero: true,
                    ticks: { callback: (v) => this.formatMoney(v) },
                },
            },
        };
    }

    // ─── Helpers ──────────────────────────────────────────────────
    formatMoney(value) {
        return new Intl.NumberFormat("fr-FR", {
            minimumFractionDigits: 2,
            maximumFractionDigits: 2,
        }).format(value || 0);
    }

    getKpiClass(value) {
        if (value > 0) return "o_kpi_positive";
        if (value < 0) return "o_kpi_negative";
        return "o_kpi_neutral";
    }

    // ─── User actions ─────────────────────────────────────────────
    onDateChange(field, ev) {
        this.state[field] = ev.target.value;
    }

    onApplyFilters() {
        this.loadData();
    }

    onResetFilters() {
        const today = new Date();
        this.state.dateFrom = `${today.getFullYear()}-01-01`;
        this.state.dateTo = `${today.getFullYear()}-12-31`;
        this.loadData();
    }

    async openFullWizard() {
        await this.action.doAction({
            type: "ir.actions.act_window",
            name: "États Financiers - Vue détaillée",
            res_model: "financial.statement.wizard",
            view_mode: "form",
            views: [[false, "form"]],
            target: "current",
            context: {
                default_date_from: this.state.dateFrom,
                default_date_to: this.state.dateTo,
            },
        });
    }
}

registry.category("actions").add("pfe_compta_dashboard", ComptaDashboard);
