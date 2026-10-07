"""Read bounded ZIP entries directly; never extract user paths to disk."""
import io, stat, zipfile
from pathlib import PurePosixPath

class ZipImportError(ValueError): pass

def import_cases(payload:bytes):
    if not payload or len(payload)>2*1024*1024: raise ZipImportError('ZIP 文件不能为空，且不能超过 2 MiB')
    try:
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            entries=archive.infolist()
            if len(entries)>400: raise ZipImportError('ZIP 包中的文件过多')
            pairs={}; seen=set(); total=0
            for info in entries:
                path=PurePosixPath(info.filename)
                if path.is_absolute() or '..' in path.parts or '\\' in info.filename or ':' in info.filename:
                    raise ZipImportError('ZIP 包包含不安全的文件路径')
                if stat.S_ISLNK(info.external_attr>>16): raise ZipImportError('ZIP 包不能包含符号链接')
                if info.flag_bits&1: raise ZipImportError('不支持加密 ZIP 包')
                if info.is_dir() or '__MACOSX' in path.parts or path.name.startswith('.'): continue
                suffix=path.suffix.lower()
                if suffix not in ('.in','.out'): continue
                if info.filename in seen: raise ZipImportError('ZIP 包包含重复文件：'+info.filename)
                seen.add(info.filename)
                key=str(path.with_suffix(''))
                if len(key)>512: raise ZipImportError('测试文件名过长')
                if suffix in pairs.get(key,{}): raise ZipImportError('同一个测试点存在重复输入或输出：'+key)
                if info.file_size>131072: raise ZipImportError('单个测试文件不能超过 128 KiB：'+info.filename)
                total+=info.file_size
                if total>1024*1024: raise ZipImportError('解压后的测试数据不能超过 1 MiB')
                with archive.open(info) as stream: data=stream.read(131073)
                if len(data)>131072: raise ZipImportError('测试文件过大')
                try: text=data.decode('utf-8')
                except UnicodeDecodeError: raise ZipImportError('测试文件必须是 UTF-8 文本：'+info.filename)
                pairs.setdefault(key,{})[suffix]=text
            if not pairs: raise ZipImportError('没有找到 .in / .out 测试文件')
            if len(pairs)>100: raise ZipImportError('最多导入 100 个测试点')
            missing=[key+(' 缺少 .out' if '.out' not in values else ' 缺少 .in') for key,values in pairs.items() if len(values)!=2]
            if missing: raise ZipImportError('文件未配对：'+ '；'.join(missing[:5]))
            return [{'name':key,'input':values['.in'],'expected_output':values['.out'],'weight':1} for key,values in sorted(pairs.items())]
    except (zipfile.BadZipFile,NotImplementedError,RuntimeError,EOFError) as e:
        raise ZipImportError('无法读取 ZIP 文件：'+str(e)) from e
