"""Tab 7: Data and Experiment Information."""
from __future__ import annotations

from pathlib import Path

from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from matplotlib.figure import Figure
from PySide6.QtWidgets import (
    QFileDialog, QGridLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit,
    QMessageBox, QPlainTextEdit, QPushButton, QVBoxLayout, QWidget,
)

from src.gui.app_context import AppContext


class DataTab(QWidget):
    def __init__(self, ctx: AppContext) -> None:
        super().__init__()
        self.ctx = ctx
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        box = QGroupBox("Experiment Information")
        grid = QGridLayout(box)
        grid.addWidget(QLabel("Experiment name:"), 0, 0)
        self.experiment_name_edit = QLineEdit("Experiment")
        grid.addWidget(self.experiment_name_edit, 0, 1)

        grid.addWidget(QLabel("Sample name:"), 0, 2)
        self.sample_name_edit = QLineEdit()
        grid.addWidget(self.sample_name_edit, 0, 3)

        grid.addWidget(QLabel("Operator name:"), 1, 0)
        self.operator_edit = QLineEdit()
        grid.addWidget(self.operator_edit, 1, 1)

        grid.addWidget(QLabel("Output folder:"), 1, 2)
        folder_row = QHBoxLayout()
        self.output_folder_edit = QLineEdit(self.ctx.settings.data_output_root)
        folder_row.addWidget(self.output_folder_edit)
        browse_btn = QPushButton("Browse...")
        browse_btn.clicked.connect(self._browse_folder)
        folder_row.addWidget(browse_btn)
        grid.addLayout(folder_row, 1, 3)

        grid.addWidget(QLabel("Sample description:"), 2, 0)
        self.description_edit = QPlainTextEdit()
        self.description_edit.setMaximumHeight(60)
        grid.addWidget(self.description_edit, 2, 1, 1, 3)

        grid.addWidget(QLabel("Notes:"), 3, 0)
        self.notes_edit = QPlainTextEdit()
        self.notes_edit.setMaximumHeight(60)
        grid.addWidget(self.notes_edit, 3, 1, 1, 3)

        layout.addWidget(box)

        create_btn = QPushButton("Create Experiment Folder")
        create_btn.clicked.connect(self._create_experiment)
        layout.addWidget(create_btn)

        self.folder_label = QLabel("No experiment folder created yet.")
        self.folder_label.setWordWrap(True)
        layout.addWidget(self.folder_label)

        colormap_box = QGroupBox("2D Color Maps (Magnitude vs. Frequency and Field)")
        cm_layout = QVBoxLayout(colormap_box)
        btn_row = QHBoxLayout()
        s11_btn = QPushButton("Generate S11 Color Map")
        s11_btn.clicked.connect(lambda: self._generate_colormap("S11"))
        s21_btn = QPushButton("Generate S21 Color Map")
        s21_btn.clicked.connect(lambda: self._generate_colormap("S21"))
        btn_row.addWidget(s11_btn)
        btn_row.addWidget(s21_btn)
        cm_layout.addLayout(btn_row)

        self.figure = Figure(figsize=(7, 4))
        self.canvas = FigureCanvasQTAgg(self.figure)
        cm_layout.addWidget(self.canvas)
        layout.addWidget(colormap_box)

    def _browse_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Select Output Folder", self.output_folder_edit.text())
        if folder:
            self.output_folder_edit.setText(folder)

    def _create_experiment(self) -> None:
        from src.data.data_manager import DataManager

        self.ctx.data_manager = DataManager(Path(self.output_folder_edit.text()), logger=self.ctx.logger)
        experiment_dir = self.ctx.data_manager.create_experiment(
            experiment_name=self.experiment_name_edit.text(),
            sample_name=self.sample_name_edit.text(),
            sample_description=self.description_edit.toPlainText(),
            operator_name=self.operator_edit.text(),
            notes=self.notes_edit.toPlainText(),
        )
        self.ctx.logger.attach_experiment_log(experiment_dir)
        if self.ctx.safety_manager.is_configured:
            self.ctx.data_manager.save_max_current(self.ctx.safety_manager.max_current)
        if self.ctx.calibration_manager.points:
            self.ctx.calibration_manager.save_csv(experiment_dir / "calibration" / "calibration.csv")
        self.folder_label.setText(f"Experiment folder: {experiment_dir}")
        QMessageBox.information(self, "Experiment Created", f"Experiment folder created:\n{experiment_dir}")

    def _generate_colormap(self, which: str) -> None:
        result = self.ctx.data_manager.build_colormap(which)
        if result is None:
            QMessageBox.warning(self, "No Data", "No measurement data available yet for a color map.")
            return
        fields, freqs, matrix = result
        self.figure.clear()
        ax = self.figure.add_subplot(111)
        mesh = ax.pcolormesh(freqs / 1e9, fields, matrix, shading="auto", cmap="viridis")
        ax.set_xlabel("Frequency (GHz)")
        ax.set_ylabel("Magnetic field (Oe)")
        ax.set_title(f"{which} Magnitude (dB)")
        self.figure.colorbar(mesh, ax=ax, label="Magnitude (dB)")
        self.canvas.draw()
        if self.ctx.data_manager.experiment_dir is not None:
            path = self.ctx.data_manager.experiment_dir / "plots" / f"{which.lower()}_colormap.png"
            self.figure.savefig(path, dpi=150)
