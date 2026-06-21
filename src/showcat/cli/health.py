from showcat.core.database import RunLedger, get_db_session


def get_health_summary() -> None:
    """Queries run_ledger and prints a stage execution status report."""
    print("=" * 95)
    print(f"{'Opener Pipeline Stage Health Summary':^95}")
    print("=" * 95)
    print(
        f"{'Stage Name':<30} | {'Status':<10} | "
        f"{'Last Run Started (UTC)':<24} | {'Processed':<10} | "
        f"{'Duration':<8}"
    )
    print("-" * 95)

    with get_db_session() as session:
        # Retrieve all distinct stages
        stages = [r[0] for r in session.query(RunLedger.stage_name).distinct().all()]

        if not stages:
            print(f"{'No stage runs recorded in the ledger yet.':^95}")
            print("=" * 95)
            return

        for stage_name in sorted(stages):
            # Fetch latest run for this stage
            latest_run = (
                session.query(RunLedger)
                .filter(RunLedger.stage_name == stage_name)
                .order_by(RunLedger.started_at.desc())
                .first()
            )

            if latest_run:
                started = latest_run.started_at.strftime("%Y-%m-%d %H:%M:%S")
                status = latest_run.status.upper()
                processed = (
                    str(latest_run.records_processed)
                    if latest_run.records_processed is not None
                    else "-"
                )

                if latest_run.ended_at and latest_run.started_at:
                    duration_secs = (latest_run.ended_at - latest_run.started_at).total_seconds()
                    duration = f"{duration_secs:.2f}s"
                else:
                    duration = "-"

                print(
                    f"{stage_name:<30} | {status:<10} | "
                    f"{started:<24} | {processed:<10} | "
                    f"{duration:<8}"
                )
                if latest_run.error_message:
                    print(f"  └─ Failure Error: {latest_run.error_message}")

    print("=" * 95)


if __name__ == "__main__":
    get_health_summary()
