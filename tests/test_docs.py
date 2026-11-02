import importlib.util
from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('wizard',ROOT/'scripts/wizard.py')
w=importlib.util.module_from_spec(spec);spec.loader.exec_module(w)

class DocsTests(unittest.TestCase):
    def test_published_card_matches_package_card(self):
        self.assertEqual((ROOT/'docs/index.html').read_bytes(),(ROOT/'assets/story-intake.html').read_bytes())

    def test_card_ships_twelve_themes_and_requires_one(self):
        html=(ROOT/'assets/story-intake.html').read_text(encoding='utf-8')
        for theme in ['婚礼爱情','求婚','纪念日 / 周年','生日 / 寿辰','周岁宴','毕业','成长记录','旅行','宠物','家人 / 亲情','工作 / 事业','品牌 / 产品']:
            self.assertIn(f"t:'{theme}'",html,theme)
        self.assertIn('<div id="themeBody" hidden></div>',html)
        self.assertIn("const KEY='story-intake-v2'",html)
        self.assertIn("searchParams.get('theme')",html)

    def test_step_table_matches_code_in_both_languages(self):
        zh=(ROOT/'SKILL.md').read_text(encoding='utf-8')
        en=(ROOT/'SKILL.en.md').read_text(encoding='utf-8')
        for i,(name_zh,name_en) in enumerate(zip(w.STEPS,w.STEPS_EN),1):
            self.assertIn(f'| {i} {name_zh} |',zh,name_zh)
            self.assertIn(f'| {i} {name_en} |',en,name_en)

    def test_gendocs_check_passes_and_rewrite_is_idempotent(self):
        import subprocess,sys
        check=subprocess.run([sys.executable,str(ROOT/'scripts/gendocs.py'),'--check'],capture_output=True,text=True)
        self.assertEqual(check.returncode,0,check.stderr)
        for doc,names in [(ROOT/'SKILL.md',w.STEPS),(ROOT/'SKILL.en.md',w.STEPS_EN)]:
            before=doc.read_text(encoding='utf-8')
            rewrite=subprocess.run([sys.executable,str(ROOT/'scripts/gendocs.py'),'--write'],capture_output=True,text=True)
            self.assertEqual(rewrite.returncode,0,rewrite.stderr)
            self.assertEqual(doc.read_text(encoding='utf-8'),before)

if __name__=='__main__':unittest.main()
