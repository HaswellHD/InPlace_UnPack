import sys

if len(sys.argv) > 1:
    from inplace_unpack.cli import main
    sys.exit(main())
else:
    from inplace_unpack.gui import main
    main()
