/** @odoo-module **/

/**
 * Chart Renderer for AI Chat
 * Renders graphs using Chart.js
 */
export class ChartRenderer {
    constructor(canvasElement, graphData) {
        this.canvas = canvasElement;
        this.data = graphData;
        this.chart = null;
    }

    render() {
        if (!window.Chart) {
            console.error("Chart.js not loaded");
            return null;
        }

        const config = {
            type: this.data.type,
            data: {
                labels: this.data.labels || [],
                datasets: (this.data.datasets || []).map(ds => ({
                    ...ds,
                    backgroundColor: this._getBackgroundColors(this.data.type, ds.data?.length || 0),
                    borderColor: this._getBorderColors(this.data.type, ds.data?.length || 0),
                    borderWidth: 2,
                    tension: 0.4  // Smooth lines for line/area charts
                }))
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    title: {
                        display: true,
                        text: this.data.title || 'Chart',
                        font: {
                            size: 16,
                            weight: 'bold'
                        },
                        color: '#212529'
                    },
                    legend: {
                        display: this.data.type === 'pie' || this.data.type === 'doughnut',
                        position: 'bottom'
                    },
                    tooltip: {
                        backgroundColor: 'rgba(0, 0, 0, 0.8)',
                        titleColor: '#fff',
                        bodyColor: '#fff',
                        borderColor: '#875a7b',
                        borderWidth: 1
                    }
                },
                scales: this._getScales(this.data.type)
            }
        };

        try {
            this.chart = new Chart(this.canvas, config);
            return this.chart;
        } catch (error) {
            console.error("Error creating chart:", error);
            return null;
        }
    }

    _getScales(type) {
        // Pie and doughnut charts don't use scales
        if (type === 'pie' || type === 'doughnut') {
            return {};
        }

        return {
            x: {
                grid: {
                    display: false
                },
                ticks: {
                    color: '#6c757d',
                    maxRotation: 45,
                    minRotation: 0
                }
            },
            y: {
                beginAtZero: true,
                grid: {
                    color: 'rgba(0, 0, 0, 0.05)'
                },
                ticks: {
                    color: '#6c757d'
                }
            }
        };
    }

    _getBackgroundColors(type, count) {
        const colors = [
            'rgba(135, 90, 123, 0.7)',
            'rgba(162, 70, 137, 0.7)',
            'rgba(109, 72, 97, 0.7)',
            'rgba(179, 90, 154, 0.7)',
            'rgba(90, 69, 97, 0.7)',
            'rgba(199, 107, 170, 0.7)',
            'rgba(74, 53, 81, 0.7)',
            'rgba(215, 124, 186, 0.7)',
            'rgba(147, 82, 125, 0.7)',
            'rgba(191, 98, 162, 0.7)'
        ];

        if (type === 'pie' || type === 'doughnut') {
            return colors.slice(0, count);
        }

        return colors[0];
    }

    _getBorderColors(type, count) {
        const colors = [
            '#875a7b',
            '#a24689',
            '#6d4861',
            '#b35a9a',
            '#5a4561',
            '#c76baa',
            '#4a3551',
            '#d77cba',
            '#93527d',
            '#bf62a2'
        ];

        if (type === 'pie' || type === 'doughnut') {
            return colors.slice(0, count);
        }

        return colors[0];
    }

    destroy() {
        if (this.chart) {
            this.chart.destroy();
            this.chart = null;
        }
    }

    update(graphData) {
        if (this.chart) {
            this.data = graphData;
            this.chart.data.labels = graphData.labels || [];
            this.chart.data.datasets = (graphData.datasets || []).map(ds => ({
                ...ds,
                backgroundColor: this._getBackgroundColors(graphData.type, ds.data?.length || 0),
                borderColor: this._getBorderColors(graphData.type, ds.data?.length || 0)
            }));
            this.chart.update();
        } else {
            this.render();
        }
    }
}
