"""Private, bounded render-only Telegram report cache for the ISOLATED test bot.

Restarts may restore already-rendered pages only. Never loads a model, reruns
an analysis, refreshes medical evidence, or republishes old prices as current.
This is not a production persistence layer or a prediction ledger.
"""
import json
import logging
import os
from pathlib import Path
import re
import secrets
import time

_TOKEN=re.compile(r"[0-9a-f]{12}\Z")
_FIELDS=("chat_id","summary","sections","section_pages","tipoff_utc",
         "quote_valid_until_utc","current_assessment_panels",
         "current_assessment_valid_until_utc","roster_review_at_utc",
         "roster_valid_until_utc","original_roster_html")
_MAX_BYTES=8*1024*1024


class DiskBackedReports(dict):
    """A dict-compatible report cache with crash-safe local page snapshots."""

    def __init__(self, directory, chat_id, *, max_age_seconds=7*86400,
                 max_files=64):
        super().__init__()
        self.directory=Path(directory)
        self.chat_id=int(chat_id)
        self.max_age_seconds=int(max_age_seconds)
        self.max_files=int(max_files)
        self.directory.mkdir(mode=0o700,parents=True,exist_ok=True)
        os.chmod(self.directory,0o700)

    def _path(self,token):
        if not isinstance(token,str) or not _TOKEN.fullmatch(token):
            raise ValueError("PREMIUM_REPORT_TOKEN_INVALID")
        return self.directory/(token+".json")

    @staticmethod
    def _valid(data, expected_chat):
        if (not isinstance(data,dict) or data.get("chat_id")!=expected_chat or
                not isinstance(data.get("summary"),str) or
                not isinstance(data.get("sections"),dict) or
                not isinstance(data.get("section_pages"),dict) or
                not all(isinstance(k,str) and isinstance(v,str)
                        for k,v in data["sections"].items()) or
                not all(isinstance(k,str) and isinstance(v,list) and
                        all(isinstance(x,str) for x in v)
                        for k,v in data["section_pages"].items()) or
                any(len(v)>_MAX_BYTES for v in data["sections"].values()) or
                any(len(v)>128 for v in data["section_pages"].values())):
            return False
        return True

    def __setitem__(self,token,entry):
        path=self._path(token)
        if not isinstance(entry,dict) or entry.get("chat_id")!=self.chat_id:
            raise ValueError("PREMIUM_REPORT_CHAT_BINDING")
        super().__setitem__(token,entry)
        payload={key:entry[key] for key in _FIELDS if key in entry}
        payload["created_at_utc"]=entry.get("_persist_created_at_utc",int(time.time()))
        if not self._valid(payload,self.chat_id):
            logging.getLogger(__name__).warning("Premium rendered session not persisted: invalid shape")
            return
        temp=None
        try:
            raw=json.dumps(payload,ensure_ascii=False,separators=(",",":"),allow_nan=False).encode("utf-8")
            if len(raw)>_MAX_BYTES:
                raise ValueError("PREMIUM_REPORT_RENDER_BUDGET")
            temp=self.directory/("."+token+"."+secrets.token_hex(8)+".tmp")
            fd=os.open(temp,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
            with os.fdopen(fd,"wb") as output:
                output.write(raw)
                output.flush()
                os.fsync(output.fileno())
            os.replace(temp,path)
            paths=sorted(self.directory.glob("[0-9a-f]"*12+".json"),
                         key=lambda item:item.stat().st_mtime,reverse=True)
            for old in paths[self.max_files:]:
                old.unlink(missing_ok=True)
        except (OSError,ValueError,TypeError) as exc:
            logging.getLogger(__name__).warning(
                "Rendered Telegram report persistence unavailable: %s",type(exc).__name__)
        finally:
            if temp is not None:temp.unlink(missing_ok=True)

    def __delitem__(self,token):
        # Explicit deletion means revocation, not an ordinary restart.
        # Without removing the file, a callback could silently reload the
        # intentionally deleted report and bypass session-expiry semantics.
        path=self._path(token)
        super().__delitem__(token)
        path.unlink(missing_ok=True)

    def pop(self,token,*args):
        if len(args)>1:
            raise TypeError("pop expected at most 2 arguments")
        if token not in self:
            if args:return args[0]
            raise KeyError(token)
        value=super().__getitem__(token)
        self.__delitem__(token)
        return value

    def clear(self):
        for token in list(self):
            self.__delitem__(token)

    def get(self,token,default=None):
        found=super().get(token)
        if found is not None:return found
        try:
            path=self._path(token)
            if not path.is_file() or path.stat().st_size>_MAX_BYTES:return default
            content=json.loads(path.read_text(encoding="utf-8"))
            created=content.get("created_at_utc")
            now=int(time.time())
            if (type(created) is not int or not 0<=now-created<=self.max_age_seconds
                    or not self._valid(content,self.chat_id)):
                return default
            entry={key:content[key] for key in _FIELDS if key in content}
            entry["_persist_created_at_utc"]=created
            entry["restored_archive_session"]=True
            # Restored pages are read-only snapshots; do not re-fetch
            # live roster or bookmaker observations using an old context.
            entry["roster_auto_ready"]=False
            super().__setitem__(token,entry)
            return entry
        except (OSError,ValueError,TypeError,UnicodeError,json.JSONDecodeError):
            return default
