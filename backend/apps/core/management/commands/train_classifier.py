from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.core.classifier_training import train_candidate


class Command(BaseCommand):
    help = "Train and evaluate a non-promoted classifier candidate from a reviewed corpus manifest."

    def add_arguments(self, parser):
        root = settings.BASE_DIR.parent
        parser.add_argument(
            "--manifest",
            type=Path,
            default=root / "data" / "classifier_corpus" / "manifest.csv",
            help="CSV manifest with approved dual-reviewed examples and leakage-safe splits.",
        )
        parser.add_argument(
            "--output-dir",
            type=Path,
            default=settings.BASE_DIR / "model_artifacts" / "candidates",
            help="Directory for versioned candidate model artifacts.",
        )
        parser.add_argument("--code-version", default="unrecorded", help="Optional source commit or release identifier.")
        parser.add_argument(
            "--allow-showcase-owner-approval",
            action="store_true",
            help="Opt in to owner-approved AI-assisted showcase annotations. The resulting artifact is marked non-production.",
        )
        parser.add_argument(
            "--calibrate-for-review",
            action="store_true",
            help="Fit sigmoid probability calibration on the calibration split and derive review thresholds from that split.",
        )

    def handle(self, *args, **options):
        try:
            artifact_dir, metadata = train_candidate(
                options["manifest"],
                options["output_dir"],
                options["code_version"],
                allow_showcase_owner_approval=options["allow_showcase_owner_approval"],
                calibrate_for_review=options["calibrate_for_review"],
            )
        except (OSError, ValueError) as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(self.style.SUCCESS(f"Candidate trained: {metadata['model_version']}"))
        self.stdout.write(f"Artifact directory: {artifact_dir}")
        self.stdout.write(f"Model metrics: {artifact_dir / 'metadata.json'}")
        self.stdout.write(f"Sealed test evaluation: {artifact_dir / 'evaluation_report.json'}")
        self.stdout.write(f"Reliability plot: {artifact_dir / 'reliability.svg'}")
        self.stdout.write(f"Promotion gate: {metadata['promotion_gate']['status']} (automatic promotion disabled)")
        self.stdout.write("Promotion status: candidate_only")
