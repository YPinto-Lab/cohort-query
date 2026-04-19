"""Primary Ask-SLM CLI entrypoint.

Usage examples:
  python askslm.py alpha-diversity --view PhagesInBlood --rank species --group Group
  python askslm.py taxonomic-abundance --view PhagesInBlood --rank genus --taxon Prevotella --group Group
  python askslm.py single-taxon-abundance --view PhagesInBlood --taxon Viruses --source-keys day_run host_subject_id_sam
  python askslm.py abundance-matrix --view PhagesInBlood
"""

from cli import build_parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
