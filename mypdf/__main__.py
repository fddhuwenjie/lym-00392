"""Allow running mypdf as a module: python -m mypdf"""

from .cli import main
import sys

if __name__ == '__main__':
    sys.exit(main())
