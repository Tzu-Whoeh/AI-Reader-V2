"""
三层产物落盘 + 路径契约
  raw层:   每章每维度每pass的原始模型输出   output/ch{NN}/{dimension}_{pass}.json
  章节归一: 每章六pass跨维度合并            output/ch{NN}/_merged.json
  全局分维度: 跨章归一,每维度一个全局文件     output/global/{dimension}.json
另存:  output/global/_index.json  顶层索引(章节清单+各全局文件+统计+校验摘要)
"""
import json, os

class Store:
    def __init__(self, root="output"):
        self.root=root
        os.makedirs(os.path.join(root,"global"), exist_ok=True)

    def _chdir(self, ch):
        d=os.path.join(self.root, f"ch{ch:02d}")
        os.makedirs(d, exist_ok=True)
        return d

    # ---- 第一层:原始 pass 输出 ----
    def save_raw(self, ch, dimension, data, pass_name=None):
        """dimension: scene|character|item|location|time ; pass_name: pass1|pass2|None"""
        fn=f"{dimension}.json" if not pass_name else f"{dimension}_{pass_name}.json"
        path=os.path.join(self._chdir(ch), fn)
        self._dump(path, data)
        return path

    # ---- 第二层:章节内归一 ----
    def save_chapter_merged(self, ch, merged):
        path=os.path.join(self._chdir(ch), "_merged.json")
        self._dump(path, merged)
        return path

    # ---- 第三层:全局分维度 ----
    def save_global(self, dimension, data):
        """dimension: characters|items|locations|timeline|scenes"""
        path=os.path.join(self.root,"global",f"{dimension}.json")
        self._dump(path, data)
        return path

    def save_index(self, index):
        path=os.path.join(self.root,"global","_index.json")
        self._dump(path, index)
        return path

    def load_chapter_merged(self, ch):
        return json.load(open(os.path.join(self.root,f"ch{ch:02d}","_merged.json"),encoding="utf-8"))

    def list_chapters(self):
        chs=[]
        for d in sorted(os.listdir(self.root)):
            if d.startswith("ch") and d[2:].isdigit(): chs.append(int(d[2:]))
        return sorted(chs)

    @staticmethod
    def _dump(path, data):
        with open(path,"w",encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
