import tkinter as tk


def _rounded_rect(canvas, x1, y1, x2, y2, radius=14, **kwargs):
    radius = max(2, min(radius, int((x2 - x1) / 2), int((y2 - y1) / 2)))
    points = [
        x1 + radius, y1,
        x2 - radius, y1,
        x2, y1,
        x2, y1 + radius,
        x2, y2 - radius,
        x2, y2,
        x2 - radius, y2,
        x1 + radius, y2,
        x1, y2,
        x1, y2 - radius,
        x1, y1 + radius,
        x1, y1,
    ]
    return canvas.create_polygon(points, smooth=True, splinesteps=24, **kwargs)


def _hex_rgb(value):
    value = value.lstrip('#')
    if len(value) != 6:
        return 0, 0, 0
    return tuple(int(value[i:i+2], 16) for i in (0, 2, 4))


def _blend_hex(base, overlay, alpha):
    """Approximate CSS rgba overlay by pre-blending against a solid Tk background."""
    br, bg, bb = _hex_rgb(base)
    or_, og, ob = _hex_rgb(overlay)
    a = max(0.0, min(1.0, float(alpha)))
    r = round(br * (1.0 - a) + or_ * a)
    g = round(bg * (1.0 - a) + og * a)
    b = round(bb * (1.0 - a) + ob * a)
    return f'#{r:02X}{g:02X}{b:02X}'


class GlowPanel(tk.Frame):
    def __init__(self, master, *, fill='#171020', border='#6425A8', glow='#B678FF', radius=18, inset=10, bg=None, **kwargs):
        parent_bg = bg or self._parent_bg(master)
        super().__init__(master, bg=parent_bg, bd=0, highlightthickness=0, **kwargs)
        self._fill = fill
        self._border = border
        self._glow = glow
        self._radius = radius
        self._inset = inset
        self.canvas = tk.Canvas(self, bg=parent_bg, highlightthickness=0, bd=0, relief='flat')
        self.canvas.pack(fill='both', expand=True)
        self.content = tk.Frame(self.canvas, bg=fill, bd=0, highlightthickness=0)
        self._window = self.canvas.create_window(inset, inset, anchor='nw', window=self.content)
        self.bind('<Configure>', self._redraw)

    @staticmethod
    def _parent_bg(master):
        for key in ('background', 'bg'):
            try:
                return master.cget(key)
            except Exception:
                pass
        return '#07060B'

    def _redraw(self, _event=None):
        w = max(20, self.winfo_width())
        h = max(20, self.winfo_height())
        c = self.canvas
        c.delete('panel')
        _rounded_rect(c, 1, 1, w - 1, h - 1, self._radius + 3, fill='', outline='#0E0A15', width=5, tags='panel')
        _rounded_rect(c, 3, 3, w - 3, h - 3, self._radius + 2, fill='', outline='#171020', width=3, tags='panel')
        _rounded_rect(c, 5, 5, w - 5, h - 5, self._radius + 1, fill='', outline='#35115D', width=2, tags='panel')
        _rounded_rect(c, 6, 6, w - 6, h - 6, self._radius, fill=self._fill, outline=self._border, width=1, tags='panel')
        c.create_line(18, 7, max(18, w - 18), 7, fill=self._glow, width=1, tags='panel')
        c.create_line(18, h - 7, max(18, w - 18), h - 7, fill='#21162E', width=1, tags='panel')
        c.coords(self._window, self._inset, self._inset)
        c.itemconfigure(self._window, width=max(1, w - self._inset * 2), height=max(1, h - self._inset * 2))
        c.tag_lower('panel')


class NeonButton(tk.Canvas):
    """Canvas button with a CSS-like layered 3D shadow.

    Requested visual recipe:
      0 8px 0 #491B76
      0 14px 24px rgba(117, 50, 190, .30)
      inset 0 1px 0 rgba(255,255,255,.30)

    Tk has no native blur/alpha box-shadow, so the soft shadow is represented
    by several pre-blended rounded layers while the 8px depth and inset
    highlight are drawn directly.
    """

    ROLE_COLORS = {
        'primary': ('#9654FF', '#B678FF', '#FAF7FF', '#D3A5FF'),
        'secondary': ('#6425A8', '#9654FF', '#FAF7FF', '#B678FF'),
        'teal': ('#B678FF', '#D3A5FF', '#07060B', '#D3A5FF'),
        'danger': ('#21162E', '#35115D', '#CFC3DA', '#6425A8'),
        'danger_live': ('#6425A8', '#9654FF', '#FAF7FF', '#D3A5FF'),
    }

    SHADOW_DEPTH = '#491B76'
    SHADOW_SOFT = '#7532BE'

    def __init__(
        self,
        master,
        text,
        command=None,
        role='primary',
        width=None,
        state='normal',
        font=('Segoe UI Semibold', 11),
        height=46,
        **kwargs,
    ):
        self._parent_bg = self._get_bg(master)
        self._text = text
        self._command = command
        self._role = role
        self._state = state
        self._hover = False
        self._pressed = False
        self._font = font
        self._face_height = int(height)
        self._shadow_extra = 18
        self._height = self._face_height + self._shadow_extra
        px_width = (width * 11 + 28) if isinstance(width, int) else max(120, len(text) * 9 + 42)

        super().__init__(
            master,
            width=px_width,
            height=self._height,
            bg=self._parent_bg,
            highlightthickness=0,
            bd=0,
            relief='flat',
            cursor='hand2' if state != 'disabled' else 'arrow',
            **kwargs,
        )
        self.bind('<Configure>', self._draw)
        self.bind('<Enter>', self._enter)
        self.bind('<Leave>', self._leave)
        self.bind('<ButtonPress-1>', self._press)
        self.bind('<ButtonRelease-1>', self._release)
        self._draw()

    @staticmethod
    def _get_bg(master):
        for key in ('background', 'bg'):
            try:
                value = master.cget(key)
                if isinstance(value, str) and value.startswith('#') and len(value) == 7:
                    return value
            except Exception:
                pass
        return '#171020'

    def _palette(self):
        role = 'danger_live' if self._role == 'danger' and self._state != 'disabled' else self._role
        base, hover, fg, glow = self.ROLE_COLORS.get(role, self.ROLE_COLORS['primary'])
        if self._state == 'disabled':
            return '#21162E', '#21162E', '#9587A3', '#35115D'
        return base, hover, fg, glow

    def _draw(self, _event=None):
        self.delete('all')
        w = max(20, self.winfo_width() or int(self['width']))
        total_h = max(28, self.winfo_height() or self._height)
        face_h = min(self._face_height, max(24, total_h - self._shadow_extra))

        base, hover, fg, glow = self._palette()
        fill = hover if self._hover and self._state != 'disabled' else base

        # Pressing the face reduces the visible 8px hard-depth layer.
        press_y = 4 if self._pressed and self._state != 'disabled' else 0
        x1, x2 = 7, w - 7
        face_top = 5 + press_y
        face_bottom = face_top + face_h - 10

        # CSS: 0 14px 24px rgba(117,50,190,.30)
        # Approximate the 24px blur using successively lighter, pre-blended
        # purple layers behind the button.
        soft_10 = _blend_hex(self._parent_bg, self.SHADOW_SOFT, 0.10)
        soft_18 = _blend_hex(self._parent_bg, self.SHADOW_SOFT, 0.18)
        soft_30 = _blend_hex(self._parent_bg, self.SHADOW_SOFT, 0.30)
        _rounded_rect(
            self, x1 - 5, face_top + 14, x2 + 5, min(total_h - 1, face_bottom + 18),
            13, fill=soft_10, outline='',
        )
        _rounded_rect(
            self, x1 - 3, face_top + 13, x2 + 3, min(total_h - 2, face_bottom + 15),
            12, fill=soft_18, outline='',
        )
        _rounded_rect(
            self, x1 - 1, face_top + 12, x2 + 1, min(total_h - 3, face_bottom + 12),
            11, fill=soft_30, outline='',
        )

        # CSS: 0 8px 0 #491B76
        depth_offset = 4 if self._pressed and self._state != 'disabled' else 8
        _rounded_rect(
            self,
            x1,
            face_top + depth_offset,
            x2,
            min(total_h - 4, face_bottom + depth_offset),
            10,
            fill=self.SHADOW_DEPTH if self._state != 'disabled' else '#35115D',
            outline='#6425A8' if self._state != 'disabled' else '#35115D',
            width=1,
        )

        # Main face.
        _rounded_rect(self, x1 - 1, face_top - 1, x2 + 1, face_bottom + 1, 11, fill='', outline='#0E0A15', width=3)
        _rounded_rect(self, x1, face_top, x2, face_bottom, 10, fill=fill, outline=glow, width=1)

        # CSS: inset 0 1px 0 rgba(255,255,255,.30)
        inset = _blend_hex(fill, '#FFFFFF', 0.30)
        self.create_line(
            x1 + 13,
            face_top + 2,
            x2 - 13,
            face_top + 2,
            fill=inset if self._state != 'disabled' else '#9587A3',
            width=1,
        )

        # Tiny lower bevel keeps the 3D face visually separated from depth.
        lower_bevel = _blend_hex(fill, '#07060B', 0.28)
        self.create_line(x1 + 14, face_bottom - 1, x2 - 14, face_bottom - 1, fill=lower_bevel, width=1)

        self.create_text(
            w / 2,
            (face_top + face_bottom) / 2 + 1,
            text=self._text,
            fill=fg,
            font=self._font,
        )

    def _enter(self, _event):
        if self._state != 'disabled':
            self._hover = True
            self._draw()

    def _leave(self, _event):
        self._hover = False
        self._pressed = False
        self._draw()

    def _press(self, _event):
        if self._state != 'disabled':
            self._pressed = True
            self._draw()

    def _release(self, event):
        if self._state == 'disabled':
            return
        inside = 0 <= event.x <= self.winfo_width() and 0 <= event.y <= self.winfo_height()
        self._pressed = False
        self._draw()
        if inside and self._command:
            self._command()

    def configure(self, cnf=None, **kwargs):
        if cnf:
            kwargs.update(cnf)
        if 'state' in kwargs:
            self._state = kwargs.pop('state')
            if self._state == 'disabled':
                self._pressed = False
            super().configure(cursor='arrow' if self._state == 'disabled' else 'hand2')
        if 'font' in kwargs:
            self._font = kwargs.pop('font')
        if 'text' in kwargs:
            self._text = kwargs.pop('text')
        if 'height' in kwargs:
            self._face_height = max(28, int(kwargs.pop('height')))
            self._height = self._face_height + self._shadow_extra
            super().configure(height=self._height)
        for k in ('padx', 'pady', 'bg', 'fg', 'activebackground', 'activeforeground',
                  'disabledforeground', 'relief', 'bd', 'cursor'):
            kwargs.pop(k, None)
        if kwargs:
            super().configure(**kwargs)
        self._draw()

    config = configure

    def cget(self, key):
        if key == 'state':
            return self._state
        if key == 'text':
            return self._text
        if key == 'height':
            return self._face_height
        return super().cget(key)


class NavButton(tk.Canvas):
    def __init__(self, master, icon, text, command, *, bg='#0E0A15', hover='#171020', active='#35115D', accent='#B678FF', fg='#CFC3DA', **kwargs):
        super().__init__(master, height=54, bg=bg, bd=0, highlightthickness=0, cursor='hand2', **kwargs)
        self._bg, self._hover_bg, self._active_bg, self._accent, self._fg = bg, hover, active, accent, fg
        self._icon, self._text, self._command = icon, text, command
        self._active = False
        self._hovered = False
        self.bind('<Configure>', self._draw)
        self.bind('<Enter>', lambda e: self._set_hover(True))
        self.bind('<Leave>', lambda e: self._set_hover(False))
        self.bind('<ButtonRelease-1>', self._click)
        self._draw()
    def _set_hover(self, value):
        self._hovered = value
        self._draw()
    def _click(self, event):
        if 0 <= event.x <= self.winfo_width() and 0 <= event.y <= self.winfo_height():
            self._command()
    def set_active(self, active):
        self._active = bool(active)
        self._draw()
    def _draw(self, _event=None):
        self.delete('all')
        w = max(50, self.winfo_width())
        h = max(40, self.winfo_height())
        if self._active:
            _rounded_rect(self, 3, 4, w - 3, h - 4, 12, fill='', outline='#0E0A15', width=4)
            _rounded_rect(self, 5, 6, w - 5, h - 6, 11, fill='#35115D', outline=self._accent, width=1)
            self.create_line(14, 8, w - 14, 8, fill='#c2a7ff', width=1)
        elif self._hovered:
            _rounded_rect(self, 5, 6, w - 5, h - 6, 11, fill=self._hover_bg, outline='#2d2b50', width=1)
        self.create_text(27, h / 2, text=self._icon, fill='#FAF7FF', font=('Segoe UI Symbol', 16))
        self.create_text(52, h / 2 + 1, text=self._text, fill='#FAF7FF' if self._active else self._fg, font=('Segoe UI Semibold', 12), anchor='w')


class MetricCard(tk.Canvas):
    ICONS = {
        'HASHRATE': ('◔', '#B678FF'),
        'AVG HASHRATE': ('∿', '#D3A5FF'),
        'PEAK HASHRATE': ('↗', '#B678FF'),
        'ACCEPTED': ('✓', '#D3A5FF'),
        'REJECTED': ('✕', '#B678FF'),
        'STALE': ('⌛', '#B678FF'),
        'SUBMITTED': ('↑', '#B678FF'),
        'ACCEPTANCE': ('◴', '#B678FF'),
        'DIFFICULTY': ('▥', '#D3A5FF'),
        'EXPECTED SHARE': ('◎', '#D3A5FF'),
        'TOTAL HASHES': ('#', '#B678FF'),
        'UPTIME': ('◷', '#D3A5FF'),
        'DEVICES': ('▦', '#B678FF'),
        'ONLINE': ('✓', '#D3A5FF'),
        'TOTAL HASHRATE': ('◔', '#B678FF'),
        'MAX TEMP': ('♨', '#B678FF'),
        'ALERTS': ('!', '#B678FF'),
        'AVG AVAIL': ('◴', '#D3A5FF'),
        'AVG HEALTH': ('♥', '#D3A5FF'),
        'OFFLINE': ('×', '#B678FF'),
    }
    def __init__(self, master, title, variable, *, bg='#07060B', fill='#171020', border='#6425A8', **kwargs):
        super().__init__(master, height=106, bg=bg, bd=0, highlightthickness=0, **kwargs)
        self._title, self._var, self._fill, self._border = title, variable, fill, border
        self.bind('<Configure>', self._draw)
        try:
            variable.trace_add('write', lambda *_: self._draw())
        except Exception:
            pass
        self._draw()
    def _draw(self, _event=None):
        self.delete('all')
        w = max(100, self.winfo_width())
        h = max(80, self.winfo_height())
        icon, color = self.ICONS.get(self._title, ('●', '#B678FF'))
        _rounded_rect(self, 1, 2, w - 1, h - 1, 16, fill='', outline='#0E0A15', width=4)
        _rounded_rect(self, 3, 4, w - 3, h - 4, 15, fill='', outline='#35115D', width=2)
        _rounded_rect(self, 5, 5, w - 5, h - 5, 14, fill=self._fill, outline=self._border, width=1)
        self.create_line(24, 6, w - 24, 6, fill='#9654FF', width=1)
        self.create_oval(16, 22, 56, 62, fill='#21162E', outline='#6425A8', width=1)
        self.create_oval(19, 25, 53, 59, fill='', outline=color, width=1)
        self.create_text(36, 42, text=icon, fill=color, font=('Segoe UI Symbol', 16))
        self.create_text(70, 30, text=self._title, fill='#CFC3DA', font=('Segoe UI Semibold', 10), anchor='w')
        value = self._var.get() if hasattr(self._var, 'get') else str(self._var)
        self.create_text(70, 68, text=value, fill='#FAF7FF', font=('Segoe UI Semibold', 16), anchor='w')
