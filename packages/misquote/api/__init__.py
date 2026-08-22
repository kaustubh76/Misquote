"""A read-only HTTP surface over the artifacts the emitters write.

The module is `service`, not `app`, and that is not cosmetic: re-exporting a
name that matches a submodule rebinds `misquote.api.app` from the module to the
FastAPI instance, so `from misquote.api import app as api` hands a caller the
application object while looking exactly like a module import. It cost a full
test file's worth of `AttributeError` before the rename.
"""

from misquote.api.service import app, artifact_names, census

__all__ = ["app", "artifact_names", "census"]
