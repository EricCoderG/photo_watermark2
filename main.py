import os
import sys
import json
import math
import shutil
from dataclasses import dataclass, asdict, field
from typing import List, Optional, Tuple

from PIL import Image, ImageDraw, ImageFont, ImageFilter

from PySide6.QtCore import Qt, QSize, QRect, QPoint
from PySide6.QtGui import (QAction, QDragEnterEvent, QDropEvent, QIcon, QImage,
                           QPainter, QPixmap, QStandardItem, QStandardItemModel)
from PySide6.QtWidgets import (
    QApplication, QWidget, QFileDialog, QListView, QLabel, QPushButton, QVBoxLayout,
    QHBoxLayout, QFormLayout, QLineEdit, QSpinBox, QComboBox, QCheckBox, QSlider,
    QMessageBox, QGroupBox, QSplitter, QProgressBar, QStyle, QGridLayout)

SUPPORTED_INPUTS = {".jpg", ".jpeg", ".png", ".bmp", ".tiff", ".tif"}
SUPPORTED_OUTPUTS = {"JPEG", "PNG"}
DEFAULT_EXPORT_DIR = os.path.join(os.getcwd(), "exports")
TEMPLATES_DIR = os.path.join(os.getcwd(), "templates")
STATE_PATH = os.path.join(os.getcwd(), "last_state.json")

# ----------------------------- 数据模型 -----------------------------

@dataclass
class ExportRule:
    mode: str = "keep"
    text: str = ""
    out_format: str = "PNG"
    jpeg_quality: int = 90
    resize_mode: str = "none"
    resize_value: int = 100

@dataclass
class TextStyle:
    text: str = "Sample Watermark"
    opacity: int = 40
    font_path: str | None = None
    font_size: int = 36
    stroke: bool = True
    stroke_width: int = 2
    stroke_color: tuple[int,int,int] = (0,0,0)
    fill_color: tuple[int,int,int] = (255,255,255)
    shadow: bool = True
    shadow_offset: tuple[int,int] = (2,2)

@dataclass
class ImageMark:
    path: str | None = None
    opacity: int = 40
    scale_percent: int = 30

@dataclass
class Layout:
    anchor: str = "center"
    offset_x: int = 0
    offset_y: int = 0
    rotation_deg: float = 0.0
    allow_drag: bool = True

@dataclass
class WatermarkConfig:
    use_text: bool = True
    text: TextStyle = field(default_factory=TextStyle)      # ✅
    use_image: bool = False
    image: ImageMark = field(default_factory=ImageMark)     # ✅
    layout: Layout = field(default_factory=Layout)          # ✅
    export: ExportRule = field(default_factory=ExportRule)  # ✅


# ----------------------------- 工具函数 -----------------------------

def ensure_dirs():
    os.makedirs(DEFAULT_EXPORT_DIR, exist_ok=True)
    os.makedirs(TEMPLATES_DIR, exist_ok=True)


def is_image_file(path: str) -> bool:
    ext = os.path.splitext(path)[1].lower()
    return ext in SUPPORTED_INPUTS


def pil_to_qpixmap(img: Image.Image) -> QPixmap:
    # 转为RGBA以简化通道
    if img.mode != "RGBA":
        img = img.convert("RGBA")
    data = img.tobytes("raw", "RGBA")
    qimg = QImage(data, img.width, img.height, QImage.Format_RGBA8888)
    return QPixmap.fromImage(qimg)


def apply_resize(img: Image.Image, rule: ExportRule) -> Image.Image:
    if rule.resize_mode == "none":
        return img
    w, h = img.size
    if rule.resize_mode == "by_width":
        new_w = max(1, int(rule.resize_value))
        new_h = max(1, int(h * new_w / w))
    elif rule.resize_mode == "by_height":
        new_h = max(1, int(rule.resize_value))
        new_w = max(1, int(w * new_h / h))
    elif rule.resize_mode == "by_percent":
        scale = max(1, int(rule.resize_value)) / 100.0
        new_w = max(1, int(w * scale))
        new_h = max(1, int(h * scale))
    else:
        return img
    return img.resize((new_w, new_h), Image.LANCZOS)


def calc_anchor_pos(base_w: int, base_h: int, mark_w: int, mark_h: int, anchor: str, offx: int, offy: int) -> Tuple[int, int]:
    # 九宫格定位
    mapping = {
        "tl": (0, 0), "tm": (base_w//2 - mark_w//2, 0), "tr": (base_w - mark_w, 0),
        "ml": (0, base_h//2 - mark_h//2), "center": (base_w//2 - mark_w//2, base_h//2 - mark_h//2), "mr": (base_w - mark_w, base_h//2 - mark_h//2),
        "bl": (0, base_h - mark_h), "bm": (base_w//2 - mark_w//2, base_h - mark_h), "br": (base_w - mark_w, base_h - mark_h)
    }
    x, y = mapping.get(anchor, (0, 0))
    return x + offx, y + offy


def draw_text_watermark(base: Image.Image, cfg: TextStyle, layout: Layout) -> Image.Image:
    img = base.convert("RGBA")
    overlay = Image.new("RGBA", img.size, (0,0,0,0))
    d = ImageDraw.Draw(overlay)

    # 字体
    try:
        if cfg.font_path and os.path.exists(cfg.font_path):
            font = ImageFont.truetype(cfg.font_path, cfg.font_size)
        else:
            # 优先使用项目根目录的字体文件
            font_name = "font.ttf"
            project_font = os.path.join(os.getcwd(), font_name)
            if os.path.exists(project_font):
                font = ImageFont.truetype(project_font, cfg.font_size)
            else:
                # macOS 等系统字体回退（
                font = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial Unicode.ttf", cfg.font_size)
    except Exception:
        font = ImageFont.load_default()

    text = cfg.text
    bbox = d.textbbox((0,0), text, font=font, stroke_width=cfg.stroke_width if cfg.stroke else 0)
    tw, th = bbox[2]-bbox[0], bbox[3]-bbox[1]

    # 先在独立图层绘制文本，便于旋转与透明
    text_layer = Image.new("RGBA", (tw+20, th+20), (0,0,0,0))
    td = ImageDraw.Draw(text_layer)

    # 阴影
    if cfg.shadow:
        sx, sy = cfg.shadow_offset
        shadow_pos = (10+sx, 10+sy)
        td.text(shadow_pos, text, font=font, fill=(0,0,0, int(255*cfg.opacity/100)))
        text_layer = text_layer.filter(ImageFilter.GaussianBlur(radius=1))

    # 描边
    if cfg.stroke:
        td.text((10,10), text, font=font, fill=(cfg.fill_color[0], cfg.fill_color[1], cfg.fill_color[2], int(255*cfg.opacity/100)),
                stroke_width=cfg.stroke_width, stroke_fill=(cfg.stroke_color[0], cfg.stroke_color[1], cfg.stroke_color[2], int(255*cfg.opacity/100)))
    else:
        td.text((10,10), text, font=font, fill=(cfg.fill_color[0], cfg.fill_color[1], cfg.fill_color[2], int(255*cfg.opacity/100)))

    # 旋转
    if abs(layout.rotation_deg) > 1e-3:
        text_layer = text_layer.rotate(layout.rotation_deg, expand=True, resample=Image.BICUBIC)

    # 定位
    bx, by = calc_anchor_pos(img.width, img.height, text_layer.width, text_layer.height, layout.anchor, layout.offset_x, layout.offset_y)
    overlay.alpha_composite(text_layer, (bx, by))

    out = Image.alpha_composite(img, overlay)
    return out


def draw_image_watermark(base: Image.Image, mark: ImageMark, layout: Layout) -> Image.Image:
    img = base.convert("RGBA")
    overlay = Image.new("RGBA", img.size, (0,0,0,0))
    if not mark.path or not os.path.exists(mark.path):
        return img
    wm = Image.open(mark.path)
    if wm.mode != "RGBA":
        wm = wm.convert("RGBA")

    # 按原图宽度比例缩放
    scale = max(1, mark.scale_percent) / 100.0
    target_w = max(1, int(img.width * scale))
    ratio = target_w / wm.width
    target_h = max(1, int(wm.height * ratio))
    wm = wm.resize((target_w, target_h), Image.LANCZOS)

    # 调整整体透明度
    alpha = wm.split()[-1]
    alpha = alpha.point(lambda a: int(a * (mark.opacity/100)))
    wm.putalpha(alpha)

    # 定位
    bx, by = calc_anchor_pos(img.width, img.height, wm.width, wm.height, layout.anchor, layout.offset_x, layout.offset_y)
    overlay.alpha_composite(wm, (bx, by))

    out = Image.alpha_composite(img, overlay)
    return out


def apply_watermark_once(img_path: str, cfg: WatermarkConfig) -> Image.Image:
    base = Image.open(img_path)
    # 输出前的尺寸调整（应用在最终导出前）—— 预览保持原图
    out = base
    if cfg.use_text:
        out = draw_text_watermark(out, cfg.text, cfg.layout)
    if cfg.use_image:
        out = draw_image_watermark(out, cfg.image, cfg.layout)
    return out


def export_image(img: Image.Image, src_path: str, export_dir: str, rule: ExportRule) -> str:
    os.makedirs(export_dir, exist_ok=True)
    base_name = os.path.splitext(os.path.basename(src_path))[0]
    ext = rule.out_format.lower()

    if rule.mode == "keep":
        name = base_name
    elif rule.mode == "prefix":
        name = f"{rule.text}{base_name}"
    elif rule.mode == "suffix":
        name = f"{base_name}{rule.text}"
    else:
        name = base_name

    out_path = os.path.join(export_dir, f"{name}.{ 'jpg' if rule.out_format=='JPEG' else 'png' }")

    # 导出前缩放（只影响导出，不影响预览）
    final_img = apply_resize(img, rule)

    if rule.out_format == "JPEG":
        if final_img.mode in ("RGBA", "LA"):
            final_img = final_img.convert("RGB")
        final_img.save(out_path, format="JPEG", quality=int(rule.jpeg_quality), subsampling=0)
    else:
        final_img.save(out_path, format="PNG")
    return out_path

# ----------------------------- UI 组件 -----------------------------
class ThumbList(QListView):
    def __init__(self):
        super().__init__()
        self.setAcceptDrops(True)
        self.setViewMode(QListView.IconMode)
        self.setIconSize(QSize(96, 96))
        self.setResizeMode(QListView.Adjust)
        self.setSpacing(8)
        self.model_ = QStandardItemModel(self)
        self.setModel(self.model_)
        self.paths: List[str] = []

    def dragEnterEvent(self, e: QDragEnterEvent):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e: QDropEvent):
        for url in e.mimeData().urls():
            p = url.toLocalFile()
            self.add_path_recursive(p)
        self.refresh_model()

    def add_path_recursive(self, p: str):
        if os.path.isdir(p):
            for root, _, files in os.walk(p):
                for f in files:
                    fp = os.path.join(root, f)
                    if is_image_file(fp):
                        self.paths.append(fp)
        elif os.path.isfile(p) and is_image_file(p):
            self.paths.append(p)

    def add_files(self, files: List[str]):
        for f in files:
            self.add_path_recursive(f)
        self.refresh_model()

    def refresh_model(self):
        self.model_.clear()
        # 去重并保持顺序
        seen = set()
        unique = []
        for p in self.paths:
            if p not in seen:
                seen.add(p)
                unique.append(p)
        self.paths = unique

        for p in self.paths:
            try:
                im = Image.open(p)
                im.thumbnail((96,96))
                pix = pil_to_qpixmap(im)
                item = QStandardItem(QIcon(pix), os.path.basename(p))
                item.setData(p)
                item.setEditable(False)
                self.model_.appendRow(item)
            except Exception:
                pass

    def current_path(self) -> Optional[str]:
        idx = self.currentIndex()
        if idx.isValid():
            item = self.model_.itemFromIndex(idx)
            return item.data()
        return self.paths[0] if self.paths else None


class PreviewCanvas(QLabel):
    def __init__(self):
        super().__init__()
        self.setAlignment(Qt.AlignCenter)
        self._pixmap: Optional[QPixmap] = None
        self._cfg: Optional[WatermarkConfig] = None
        self._current_img_path: Optional[str] = None

        # 拖拽移动偏移（相对anchor）
        self.dragging = False
        self.last_pos: Optional[QPoint] = None

    def set_config(self, cfg: WatermarkConfig):
        self._cfg = cfg
        self.update_preview()

    def set_image(self, path: Optional[str]):
        self._current_img_path = path
        self.update_preview()

    def update_preview(self):
        if not self._current_img_path or not self._cfg:
            self.setText("将图片拖拽到左侧列表，或点击\"导入\"按钮")
            return
        try:
            im = apply_watermark_once(self._current_img_path, self._cfg)
            # 适配label大小
            w = self.width() if self.width()>10 else 800
            h = self.height() if self.height()>10 else 600
            im_copy = im.copy()
            im_copy.thumbnail((w, h))
            self._pixmap = pil_to_qpixmap(im_copy)
            self.setPixmap(self._pixmap)
        except Exception as e:
            self.setText(f"预览失败: {e}")

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self.update_preview()

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton and self._cfg and self._cfg.layout.allow_drag:
            self.dragging = True
            self.last_pos = e.pos()

    def mouseMoveEvent(self, e):
        if self.dragging and self._cfg and self._cfg.layout.allow_drag:
            delta = e.pos() - self.last_pos
            self.last_pos = e.pos()
            self._cfg.layout.offset_x += int(delta.x())
            self._cfg.layout.offset_y += int(delta.y())
            self.update_preview()

    def mouseReleaseEvent(self, e):
        self.dragging = False


# ----------------------------- 主窗口 -----------------------------
class MainWindow(QWidget):
    def __init__(self):
        super().__init__()
        ensure_dirs()
        self.setWindowTitle("批量图片加水印 - MVP")
        self.resize(1280, 800)

        self.cfg = self.load_last_state() or WatermarkConfig()
        self.export_dir = DEFAULT_EXPORT_DIR

        # 左：缩略图列表 右：预览 + 控件表单
        self.list_view = ThumbList()
        self.preview = PreviewCanvas()
        self.preview.set_config(self.cfg)

        left = QVBoxLayout()
        btn_import = QPushButton("导入图片/文件夹…")
        btn_import.clicked.connect(self.on_import)
        left.addWidget(btn_import)
        left.addWidget(self.list_view)

        # 控制面板
        ctrl = self.build_controls()

        right = QVBoxLayout()
        right.addWidget(self.preview, stretch=1)
        right.addWidget(ctrl, stretch=0)

        splitter = QSplitter()
        lw = QWidget(); lw.setLayout(left)
        rw = QWidget(); rw.setLayout(right)
        splitter.addWidget(lw)
        splitter.addWidget(rw)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)

        root = QVBoxLayout(self)
        root.addWidget(splitter)

        # 信号
        self.list_view.clicked.connect(self.on_select)

        # 启动即刷新预览
        self.preview.set_image(self.list_view.current_path())

    # ---------------- 控件面板 ----------------
    def build_controls(self) -> QWidget:
        box = QGroupBox("参数设置")
        grid = QGridLayout()
        r = 0

        # —— 水印开关
        self.chk_text = QCheckBox("文本水印")
        self.chk_text.setChecked(self.cfg.use_text)
        self.chk_text.stateChanged.connect(self.on_change)
        grid.addWidget(self.chk_text, r, 0, 1, 1); r+=1

        # 文本内容与样式
        self.edt_text = QLineEdit(self.cfg.text.text)
        self.edt_text.textChanged.connect(self.on_change)
        grid.addWidget(QLabel("文本内容"), r,0); grid.addWidget(self.edt_text, r,1,1,3); r+=1

        self.sld_text_op = QSlider(Qt.Horizontal); self.sld_text_op.setRange(0,100); self.sld_text_op.setValue(self.cfg.text.opacity)
        self.sld_text_op.valueChanged.connect(self.on_change)
        grid.addWidget(QLabel("文本透明度"), r,0); grid.addWidget(self.sld_text_op, r,1,1,3); r+=1

        self.spn_font = QSpinBox(); self.spn_font.setRange(8, 256); self.spn_font.setValue(self.cfg.text.font_size)
        self.spn_font.valueChanged.connect(self.on_change)
        grid.addWidget(QLabel("字号"), r,0); grid.addWidget(self.spn_font, r,1); r+=1

        self.chk_stroke = QCheckBox("描边"); self.chk_stroke.setChecked(self.cfg.text.stroke)
        self.chk_stroke.stateChanged.connect(self.on_change)
        grid.addWidget(self.chk_stroke, r,0)
        self.spn_stroke_w = QSpinBox(); self.spn_stroke_w.setRange(0, 10); self.spn_stroke_w.setValue(self.cfg.text.stroke_width)
        self.spn_stroke_w.valueChanged.connect(self.on_change)
        grid.addWidget(QLabel("描边宽度"), r,1); grid.addWidget(self.spn_stroke_w, r,2); r+=1

        # —— 图片水印
        self.chk_img = QCheckBox("图片水印")
        self.chk_img.setChecked(self.cfg.use_image)
        self.chk_img.stateChanged.connect(self.on_change)
        grid.addWidget(self.chk_img, r, 0); r+=1

        self.btn_pick_img = QPushButton("选择水印图片 (PNG)")
        self.btn_pick_img.clicked.connect(self.on_pick_mark_img)
        grid.addWidget(self.btn_pick_img, r,0,1,2)
        self.sld_img_op = QSlider(Qt.Horizontal); self.sld_img_op.setRange(0,100); self.sld_img_op.setValue(self.cfg.image.opacity)
        self.sld_img_op.valueChanged.connect(self.on_change)
        grid.addWidget(QLabel("图片透明度"), r,2); grid.addWidget(self.sld_img_op, r,3); r+=1

        self.spn_img_scale = QSpinBox(); self.spn_img_scale.setRange(1, 200); self.spn_img_scale.setValue(self.cfg.image.scale_percent)
        self.spn_img_scale.valueChanged.connect(self.on_change)
        grid.addWidget(QLabel("图片宽度比例%"), r,0); grid.addWidget(self.spn_img_scale, r,1); r+=1

        # —— 布局
        self.cmb_anchor = QComboBox(); self.cmb_anchor.addItems(["tl","tm","tr","ml","center","mr","bl","bm","br"])
        self.cmb_anchor.setCurrentText(self.cfg.layout.anchor)
        self.cmb_anchor.currentTextChanged.connect(self.on_change)
        grid.addWidget(QLabel("九宫格位置"), r,0); grid.addWidget(self.cmb_anchor, r,1)

        self.spn_offx = QSpinBox(); self.spn_offx.setRange(-5000,5000); self.spn_offx.setValue(self.cfg.layout.offset_x)
        self.spn_offy = QSpinBox(); self.spn_offy.setRange(-5000,5000); self.spn_offy.setValue(self.cfg.layout.offset_y)
        self.spn_offx.valueChanged.connect(self.on_change); self.spn_offy.valueChanged.connect(self.on_change)
        grid.addWidget(QLabel("偏移X"), r,2); grid.addWidget(self.spn_offx, r,3); r+=1
        grid.addWidget(QLabel("偏移Y"), r,2); grid.addWidget(self.spn_offy, r,3); r+=1

        self.spn_rotate = QSpinBox(); self.spn_rotate.setRange(-180,180); self.spn_rotate.setValue(int(self.cfg.layout.rotation_deg))
        self.spn_rotate.valueChanged.connect(self.on_change)
        grid.addWidget(QLabel("旋转(°)"), r,0); grid.addWidget(self.spn_rotate, r,1); r+=1

        # —— 导出
        self.cmb_mode = QComboBox(); self.cmb_mode.addItems(["keep","prefix","suffix"]); self.cmb_mode.setCurrentText(self.cfg.export.mode)
        self.cmb_mode.currentTextChanged.connect(self.on_change)
        self.edt_rule = QLineEdit(self.cfg.export.text)
        self.edt_rule.textChanged.connect(self.on_change)
        grid.addWidget(QLabel("命名规则"), r,0); grid.addWidget(self.cmb_mode, r,1); grid.addWidget(self.edt_rule, r,2,1,2); r+=1

        self.cmb_format = QComboBox(); self.cmb_format.addItems(sorted(SUPPORTED_OUTPUTS)); self.cmb_format.setCurrentText(self.cfg.export.out_format)
        self.cmb_format.currentTextChanged.connect(self.on_change)
        self.spn_quality = QSpinBox(); self.spn_quality.setRange(0,100); self.spn_quality.setValue(self.cfg.export.jpeg_quality)
        self.spn_quality.valueChanged.connect(self.on_change)
        grid.addWidget(QLabel("输出格式"), r,0); grid.addWidget(self.cmb_format, r,1)
        grid.addWidget(QLabel("JPEG质量"), r,2); grid.addWidget(self.spn_quality, r,3); r+=1

        self.cmb_resize = QComboBox(); self.cmb_resize.addItems(["none","by_width","by_height","by_percent"]) ; self.cmb_resize.setCurrentText(self.cfg.export.resize_mode)
        self.cmb_resize.currentTextChanged.connect(self.on_change)
        self.spn_resize = QSpinBox(); self.spn_resize.setRange(1,10000); self.spn_resize.setValue(self.cfg.export.resize_value)
        self.spn_resize.valueChanged.connect(self.on_change)
        grid.addWidget(QLabel("导出尺寸"), r,0); grid.addWidget(self.cmb_resize, r,1); grid.addWidget(self.spn_resize, r,2); r+=1

        self.btn_export_dir = QPushButton("选择导出文件夹…")
        self.btn_export_dir.clicked.connect(self.on_pick_export_dir)
        self.lbl_export_dir = QLabel(self.elide(DEFAULT_EXPORT_DIR))
        grid.addWidget(self.btn_export_dir, r,0,1,1); grid.addWidget(self.lbl_export_dir, r,1,1,3); r+=1

        # —— 模板
        self.btn_save_tpl = QPushButton("保存为模板…")
        self.btn_save_tpl.clicked.connect(self.on_save_template)
        self.btn_load_tpl = QPushButton("加载模板…")
        self.btn_load_tpl.clicked.connect(self.on_load_template)
        grid.addWidget(self.btn_save_tpl, r,0,1,2); grid.addWidget(self.btn_load_tpl, r,2,1,2); r+=1

        # —— 批量导出
        self.btn_export = QPushButton("批量导出")
        self.btn_export.clicked.connect(self.on_export_all)
        self.progress = QProgressBar(); self.progress.setRange(0,100)
        grid.addWidget(self.btn_export, r,0,1,1); grid.addWidget(self.progress, r,1,1,3); r+=1

        box.setLayout(grid)
        return box

    # ---------------- 事件处理 ----------------
    def on_import(self):
        files, _ = QFileDialog.getOpenFileNames(self, "选择图片(可多选)", os.getcwd(), "Images (*.jpg *.jpeg *.png *.bmp *.tif *.tiff)")
        if files:
            self.list_view.add_files(files)
            self.preview.set_image(self.list_view.current_path())

    def on_select(self):
        self.preview.set_image(self.list_view.current_path())

    def on_change(self):
        # 拉取控件值写回cfg
        self.cfg.use_text = self.chk_text.isChecked()
        self.cfg.text.text = self.edt_text.text()
        self.cfg.text.opacity = self.sld_text_op.value()
        self.cfg.text.font_size = self.spn_font.value()
        self.cfg.text.stroke = self.chk_stroke.isChecked()
        self.cfg.text.stroke_width = self.spn_stroke_w.value()

        self.cfg.use_image = self.chk_img.isChecked()
        self.cfg.image.opacity = self.sld_img_op.value()
        self.cfg.image.scale_percent = self.spn_img_scale.value()

        self.cfg.layout.anchor = self.cmb_anchor.currentText()
        self.cfg.layout.offset_x = self.spn_offx.value()
        self.cfg.layout.offset_y = self.spn_offy.value()
        self.cfg.layout.rotation_deg = float(self.spn_rotate.value())

        self.cfg.export.mode = self.cmb_mode.currentText()
        self.cfg.export.text = self.edt_rule.text()
        self.cfg.export.out_format = self.cmb_format.currentText()
        self.cfg.export.jpeg_quality = self.spn_quality.value()
        self.cfg.export.resize_mode = self.cmb_resize.currentText()
        self.cfg.export.resize_value = self.spn_resize.value()

        self.preview.set_config(self.cfg)
        self.save_last_state()

    def on_pick_mark_img(self):
        file, _ = QFileDialog.getOpenFileName(self, "选择水印图片 (建议PNG)", os.getcwd(), "Images (*.png *.jpg *.jpeg *.bmp *.tif *.tiff)")
        if file:
            self.cfg.image.path = file
            self.preview.set_config(self.cfg)
            self.save_last_state()

    def on_pick_export_dir(self):
        d = QFileDialog.getExistingDirectory(self, "选择导出目录", os.getcwd())
        if d:
            # 禁止导出到原图所在目录：此处仅做轻提示，真正检查在导出时逐张校验
            self.export_dir = d
            self.lbl_export_dir.setText(self.elide(d))

    def on_export_all(self):
        if not self.list_view.paths:
            QMessageBox.information(self, "提示", "请先导入图片")
            return
        # 批量处理
        n = len(self.list_view.paths)
        for i, p in enumerate(self.list_view.paths, start=1):
            # 检查禁止导出到原目录
            src_dir = os.path.dirname(p)
            if os.path.abspath(src_dir) == os.path.abspath(self.export_dir):
                QMessageBox.warning(self, "警告", f"禁止将 {os.path.basename(p)} 导出到源目录：{src_dir}")
                continue
            try:
                im = apply_watermark_once(p, self.cfg)
                out_path = export_image(im, p, self.export_dir, self.cfg.export)
            except Exception as e:
                print("导出失败", p, e)
            self.progress.setValue(int(i/n*100))
        QMessageBox.information(self, "完成", f"已处理 {n} 张图片。")

    def on_save_template(self):
        name, ok = QFileDialog.getSaveFileName(self, "保存模板为…", TEMPLATES_DIR, "JSON (*.json)")
        if ok and name:
            cfg_dict = asdict(self.cfg)
            with open(name, "w", encoding="utf-8") as f:
                json.dump(cfg_dict, f, ensure_ascii=False, indent=2)
            QMessageBox.information(self, "提示", "模板已保存")

    def on_load_template(self):
        name, _ = QFileDialog.getOpenFileName(self, "加载模板", TEMPLATES_DIR, "JSON (*.json)")
        if name:
            with open(name, "r", encoding="utf-8") as f:
                d = json.load(f)
            self.cfg = WatermarkConfig(**{
                'use_text': d.get('use_text', True),
                'text': TextStyle(**d.get('text', {})),
                'use_image': d.get('use_image', False),
                'image': ImageMark(**d.get('image', {})),
                'layout': Layout(**d.get('layout', {})),
                'export': ExportRule(**d.get('export', {})),
            })
            self.preview.set_config(self.cfg)
            # 回填控件
            self.chk_text.setChecked(self.cfg.use_text)
            self.edt_text.setText(self.cfg.text.text)
            self.sld_text_op.setValue(self.cfg.text.opacity)
            self.spn_font.setValue(self.cfg.text.font_size)
            self.chk_stroke.setChecked(self.cfg.text.stroke)
            self.spn_stroke_w.setValue(self.cfg.text.stroke_width)

            self.chk_img.setChecked(self.cfg.use_image)
            self.sld_img_op.setValue(self.cfg.image.opacity)
            self.spn_img_scale.setValue(self.cfg.image.scale_percent)

            self.cmb_anchor.setCurrentText(self.cfg.layout.anchor)
            self.spn_offx.setValue(self.cfg.layout.offset_x)
            self.spn_offy.setValue(self.cfg.layout.offset_y)
            self.spn_rotate.setValue(int(self.cfg.layout.rotation_deg))

            self.cmb_mode.setCurrentText(self.cfg.export.mode)
            self.edt_rule.setText(self.cfg.export.text)
            self.cmb_format.setCurrentText(self.cfg.export.out_format)
            self.spn_quality.setValue(self.cfg.export.jpeg_quality)
            self.cmb_resize.setCurrentText(self.cfg.export.resize_mode)
            self.spn_resize.setValue(self.cfg.export.resize_value)

            self.save_last_state()

    # ---------------- 状态持久化 ----------------
    def save_last_state(self):
        try:
            with open(STATE_PATH, "w", encoding="utf-8") as f:
                json.dump(asdict(self.cfg), f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def load_last_state(self) -> Optional[WatermarkConfig]:
        if not os.path.exists(STATE_PATH):
            return None
        try:
            with open(STATE_PATH, "r", encoding="utf-8") as f:
                d = json.load(f)
            return WatermarkConfig(**{
                'use_text': d.get('use_text', True),
                'text': TextStyle(**d.get('text', {})),
                'use_image': d.get('use_image', False),
                'image': ImageMark(**d.get('image', {})),
                'layout': Layout(**d.get('layout', {})),
                'export': ExportRule(**d.get('export', {})),
            })
        except Exception:
            return None

    @staticmethod
    def elide(path: str, max_len: int = 60) -> str:
        if len(path) <= max_len:
            return path
        return path[:max_len//2-2] + "…" + path[-max_len//2+2:]


# ---------------- 入口 ----------------
if __name__ == '__main__':
    app = QApplication(sys.argv)
    win = MainWindow()
    win.show()
    sys.exit(app.exec())