"""Primary Ask-SLM CLI entrypoint.

Usage examples:
    python askslm.py alpha-diversity --workspace PhagesInBlood --rank species --group Group
    python askslm.py taxonomic-abundance --workspace PhagesInBlood --rank genus --taxon Prevotella --group Group
    python askslm.py single-taxon-abundance --workspace PhagesInBlood --taxon Viruses --source-keys day_run host_subject_id_sam
    python askslm.py abundance-matrix --workspace PhagesInBlood
"""

from cli import build_parser, _resolve_runtime_paths


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    if args.command != "init":
        _resolve_runtime_paths(args)
    args.func(args)


if __name__ == "__main__":
    main()
