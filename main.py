import pygame
import random
import heapq
import math
import struct
import wave
import os
import threading
import json
import time
import sys
import tempfile

# --- MQTT Setup ---
try:
    import paho.mqtt.client as mqtt
    from paho.mqtt.enums import CallbackAPIVersion
    HAS_MQTT = True
except:
    HAS_MQTT = False

# --- Config ---
LOGIC_W = 540
LOGIC_H = 960
GRID_SIZE = 31
CELL_SIZE = 16
MARGIN = 1
MAP_PX = GRID_SIZE * (CELL_SIZE + MARGIN) + MARGIN

# Colors
C_BG = (10, 10, 18)
C_GRID = (25, 30, 40)
C_WALL = (60, 65, 80)
C_SEEKER = (0, 255, 255)
C_HIDER = (255, 0, 100)
C_PATH = (0, 255, 150)
C_BTN_NORMAL = (40, 50, 60)
C_BTN_ACTIVE = (80, 100, 120)
C_BTN_TEXT = (220, 220, 220)

# MQTT
MQTT_BROKER = "broker.emqx.io"
MQTT_PORT = 1883
TOPIC_PREFIX = "shadowpath/mobile/v1/"

# --- Utils ---
def generate_sfx(filename, freq, duration, vol=0.3):
    sample_rate = 44100
    n_samples = int(sample_rate * duration)
    data = []
    for i in range(n_samples):
        t = float(i) / sample_rate
        cf = freq * (1 - t/duration * 0.5)
        v = math.sin(2 * math.pi * cf * t)
        val = int(v * vol * 32767)
        data.append(struct.pack('h', max(-32767, min(32767, val))))
    
    path = os.path.join(tempfile.gettempdir(), filename)
    try:
        with wave.open(path, 'w') as f:
            f.setparams((1, 2, sample_rate, n_samples, 'NONE', 'not compressed'))
            f.writeframes(b''.join(data))
    except: pass
    return path

# --- UI ---
class TouchButton:
    def __init__(self, x, y, w, h, text, color, cb, font, desc=""):
        self.rect = pygame.Rect(x, y, w, h)
        self.text = text
        self.color = color
        self.cb = cb
        self.font = font
        self.desc = desc # Skill description
        self.clicked = False
        self.press_start = 0

    def draw(self, screen):
        col = (min(255, self.color[0]+30), min(255, self.color[1]+30), min(255, self.color[2]+30)) if self.clicked else self.color
        pygame.draw.rect(screen, col, self.rect, 0, 8)
        pygame.draw.rect(screen, (200,200,200), self.rect, 2, 8)
        if self.text:
            s = self.font.render(self.text, True, C_BTN_TEXT)
            screen.blit(s, (self.rect.centerx - s.get_width()//2, self.rect.centery - s.get_height()//2))

    def check_down(self, pos):
        if self.rect.collidepoint(pos):
            self.clicked = True
            self.press_start = time.time()
            return True
        return False

    def check_up(self, pos):
        if self.clicked:
            # Check if it was a long press (>0.5s)
            is_long_press = (time.time() - self.press_start > 0.5)
            self.clicked = False
            
            # Only trigger action if it wasn't a long press (and released inside button)
            if self.rect.collidepoint(pos) and not is_long_press:
                if self.cb: self.cb()

class VirtualDPad:
    def __init__(self, x, y, size, cb):
        self.x, self.y = x, y
        self.size = size
        self.cb = cb
        self.btn_size = size // 3
        bs = self.btn_size
        self.rects = {
            'UP': pygame.Rect(x + bs, y, bs, bs),
            'DOWN': pygame.Rect(x + bs, y + bs*2, bs, bs),
            'LEFT': pygame.Rect(x, y + bs, bs, bs),
            'RIGHT': pygame.Rect(x + bs*2, y + bs, bs, bs)
        }
        self.pressed = None

    def draw(self, screen):
        for k, r in self.rects.items():
            col = C_BTN_ACTIVE if self.pressed == k else C_BTN_NORMAL
            pygame.draw.rect(screen, col, r, 0, 5)
            pygame.draw.rect(screen, (100,100,100), r, 2, 5)
            cx, cy = r.centerx, r.centery
            if k=='UP': pygame.draw.polygon(screen, C_BTN_TEXT, [(cx, cy-5), (cx-5, cy+5), (cx+5, cy+5)])
            elif k=='DOWN': pygame.draw.polygon(screen, C_BTN_TEXT, [(cx, cy+5), (cx-5, cy-5), (cx+5, cy-5)])
            elif k=='LEFT': pygame.draw.polygon(screen, C_BTN_TEXT, [(cx-5, cy), (cx+5, cy-5), (cx+5, cy+5)])
            elif k=='RIGHT': pygame.draw.polygon(screen, C_BTN_TEXT, [(cx+5, cy), (cx-5, cy-5), (cx-5, cy+5)])

    def check_down(self, pos):
        for k, r in self.rects.items():
            if r.collidepoint(pos):
                self.pressed = k
                if self.cb: self.cb(k)
                return True
        return False

    def check_up(self, pos):
        self.pressed = None

# --- Network ---
class MqttMgr:
    def __init__(self):
        self.client = None; self.room_id = None; self.role = None
        self.connected = False; self.msg_queue = []; self.lock = threading.Lock()
        self.status = "Disconnected"

    def init_client(self):
        if not HAS_MQTT: self.status = "Error: No paho-mqtt"; return False
        if self.client: return True
        try:
            cid = f"m_user_{random.randint(1000,9999)}_{int(time.time())}"
            try: self.client = mqtt.Client(CallbackAPIVersion.VERSION2, client_id=cid)
            except: self.client = mqtt.Client(client_id=cid)
            self.client.on_connect = self.on_connect
            self.client.on_message = self.on_message
            self.client.connect(MQTT_BROKER, MQTT_PORT, 60)
            self.client.loop_start()
            return True
        except Exception as e: self.status = "Conn Failed"; print(e); return False

    def on_connect(self, c, u, f, rc, p=None):
        if rc == 0:
            self.connected = True; self.status = "Connected"
            if self.room_id: self._sub()
        else: self.status = f"Conn Err {rc}"

    def create_room(self):
        if not self.init_client(): return None
        self.room_id = str(random.randint(1000, 9999))
        self.role = "HOST"; self._sub(); return self.room_id

    def join_room(self, rid):
        if not self.init_client(): return False
        self.room_id = rid; self.role = "JOIN"; self._sub()
        threading.Thread(target=self._send_join, daemon=True).start()
        return True

    def _sub(self):
        topic = f"{TOPIC_PREFIX}{self.room_id}/{'c2s' if self.role == 'HOST' else 's2c'}"
        self.client.subscribe(topic)

    def _send_join(self):
        for _ in range(5):
            if self.connected: self.send({"type":"HELLO"}); break
            time.sleep(0.5)

    def on_message(self, c, u, msg):
        try:
            p = json.loads(msg.payload.decode())
            with self.lock: self.msg_queue.append(p)
        except: pass

    def send(self, d):
        if not self.client or not self.room_id: return
        t = f"{TOPIC_PREFIX}{self.room_id}/{'s2c' if self.role == 'HOST' else 'c2s'}"
        self.client.publish(t, json.dumps(d))

    def get_msg(self):
        with self.lock: return self.msg_queue.pop(0) if self.msg_queue else None
    
    def close(self):
        if self.client: self.client.loop_stop(); self.client.disconnect()

# --- Main App ---
class ShadowMobile:
    def __init__(self):
        pygame.init()
        pygame.mixer.init()
        
        self.info = pygame.display.Info()
        if self.info.current_w > self.info.current_h:
            self.win_w, self.win_h = 450, 800
        else:
            self.win_w, self.win_h = self.info.current_w, self.info.current_h
            
        self.screen = pygame.display.set_mode((self.win_w, self.win_h))
        pygame.display.set_caption("SHADOW PATH MOBILE")
        
        self.scale = min(self.win_w / LOGIC_W, self.win_h / LOGIC_H)
        self.offset_x = (self.win_w - MAP_PX * self.scale) // 2
        self.offset_y = 60 * self.scale
        
        self.clock = pygame.time.Clock()
        self.font = pygame.font.Font(None, 24)
        self.font_big = pygame.font.Font(None, 48)
        
        self.init_sounds()
        self.net = MqttMgr()
        self.state = "MENU"
        self.mode = "LOCAL"
        self.my_role = "BOTH"
        
        self.input_buf = ""
        self.init_ui()
        self.reset_game()

    def init_ui(self):
        w, h = 140, 60
        cx = LOGIC_W // 2
        
        self.btns_menu = [
            TouchButton(cx-w, 400, w*2, h, "Local Game", C_BTN_NORMAL, lambda: self.start("LOCAL"), self.font),
            TouchButton(cx-w, 500, w*2, h, "Online", C_BTN_NORMAL, lambda: self.to_lobby(), self.font),
            TouchButton(cx-w, 600, w*2, h, "Exit", (80,40,40), lambda: self.quit_game(), self.font)
        ]
        
        self.btns_lobby = [
            TouchButton(cx-w, 300, w*2, h, "Create Room", C_BTN_NORMAL, lambda: self.host_game(), self.font),
            TouchButton(cx-w, 600, w*2, h, "Join Room", C_BTN_NORMAL, lambda: self.join_game(), self.font),
            TouchButton(20, 800, 120, 50, "Back", (80,40,40), lambda: self.set_state("MENU"), self.font)
        ]
        self.lobby_numpad = []
        for i in range(10):
            bx = cx - 120 + (i%5)*60
            by = 400 + (i//5)*60
            self.lobby_numpad.append(TouchButton(bx, by, 50, 50, str(i), C_BTN_NORMAL, lambda n=str(i): self.on_num(n), self.font))
        self.lobby_numpad.append(TouchButton(cx-120, 520, 110, 50, "Clear", (80,40,40), lambda: self.on_num("CLR"), self.font))
        self.lobby_numpad.append(TouchButton(cx+10, 520, 110, 50, "Del", (80,40,40), lambda: self.on_num("BS"), self.font))

        self.game_ui_group = []
        self.dpad = VirtualDPad(20, LOGIC_H - 220, 210, self.on_dpad)
        
        sx, sy = LOGIC_W - 100, LOGIC_H - 240
        self.btn_skill_q = TouchButton(sx, sy, 80, 50, "Phase(Q)", C_HIDER, lambda: self.on_skill("PHASE"), self.font, "Phase: Ignore walls (1 turn). CD:6")
        self.btn_skill_1 = TouchButton(sx, sy+60, 80, 50, "Decoy(1)", C_HIDER, lambda: self.on_skill("DECOY"), self.font, "Decoy: Fake signal nearby. CD:4")
        self.btn_skill_2 = TouchButton(sx, sy+120, 80, 50, "Silent(2)", C_HIDER, lambda: self.on_skill("SILENT"), self.font, "Silent: No heat trace (3 steps). CD:5")
        
        self.btn_radar = TouchButton(sx, sy, 80, 60, "Radar(R)", C_SEEKER, lambda: self.on_radar(), self.font, "Radar: Scan 7x7 area. CD:3")
        self.btn_confirm = TouchButton(sx, sy+80, 80, 80, "CATCH!", (200, 50, 50), lambda: self.on_confirm(), self.font, "Confirm current path to catch!")
        
        self.btn_back = TouchButton(20, 20, 80, 30, "Exit", (50,50,50), lambda: self.set_state("MENU"), self.font)

    def init_sounds(self):
        try:
            p1 = generate_sfx('ping.wav', 880, 0.1)
            p2 = generate_sfx('error.wav', 220, 0.3)
            p3 = generate_sfx('win.wav', 1200, 0.5)
            self.sfx = {'ping': pygame.mixer.Sound(p1), 'error': pygame.mixer.Sound(p2), 'win': pygame.mixer.Sound(p3)}
        except: self.sfx = {}

    def play(self, n): 
        if n in self.sfx: self.sfx[n].play()

    def set_state(self, s):
        self.state = s
        if s == "MENU": 
            self.net.close(); self.net = MqttMgr()
            self.input_buf = ""

    def quit_game(self):
        self.net.close()
        pygame.quit()
        sys.exit()

    def start(self, m):
        self.mode = m
        self.state = "PLAYING"
        self.reset_game()
        if m == "LOCAL": self.init_map(random.randint(0,9999))

    def to_lobby(self): self.set_state("LOBBY")
    
    def on_num(self, n):
        if n=="BS": self.input_buf = self.input_buf[:-1]
        elif n=="CLR": self.input_buf = ""
        else: 
            if len(self.input_buf)<4: self.input_buf += n

    def host_game(self):
        rid = self.net.create_room()
        if rid: self.input_buf = rid; self.my_role = "SEEKER"
    
    def join_game(self):
        if len(self.input_buf)!=4: return
        if self.net.join_room(self.input_buf): self.my_role = "HIDER"

    def reset_game(self):
        self.turn=1; self.max_turns=30; self.round_state="HIDER_MOVE"
        self.logs=["Waiting..."]
        self.walls=set(); self.probes={}; self.visible=set(); self.path=[]
        self.heat=[[0.0]*GRID_SIZE for _ in range(GRID_SIZE)]
        self.seeker=[15,15]; self.hider=[0,0]
        self.h_cd=0; self.h_phase=False; self.h_decoy=None; self.h_decoy_t=0; self.h_silent=0; self.h_used=False
        self.s_cd=0; self.s_used=False; self.radar=None
        self.msg=""

    def init_map(self, seed):
        random.seed(seed)
        self.walls.clear(); self.visible.clear()
        for _ in range(int(GRID_SIZE**2 * 0.12)):
            x,y = random.randint(0,30), random.randint(0,30)
            if abs(x-15)>2 or abs(y-15)>2: self.walls.add((x,y))
        self.hider = self.find_empty()
        self.reveal([15,15], 2)
        self.logs=["Game Start!"]
        self.turn=1; self.round_state="HIDER_MOVE"

    def find_empty(self):
        while True:
            x,y = random.randint(0,30), random.randint(0,30)
            if (x,y) not in self.walls: return [x,y]

    def reveal(self, p, r):
        for x in range(p[0]-r, p[0]+r+1):
            for y in range(p[1]-r, p[1]+r+1):
                if 0<=x<GRID_SIZE and 0<=y<GRID_SIZE: self.visible.add((x,y))

    def a_star(self, start, goal):
        def h(a, b): return abs(a[0]-b[0]) + abs(a[1]-b[1])
        opens = [(0, start)]; cost = {start:0}
        while opens:
            _, c = heapq.heappop(opens)
            if c == goal: return cost[c]
            for dx,dy in [(0,1),(0,-1),(1,0),(-1,0)]:
                n = (c[0]+dx, c[1]+dy)
                if 0<=n[0]<GRID_SIZE and 0<=n[1]<GRID_SIZE and n not in self.walls:
                    nc = cost[c]+1
                    if n not in cost or nc < cost[n]:
                        cost[n]=nc; heapq.heappush(opens, (nc+h(n,goal), n))
        return 999

    def on_dpad(self, d):
        if self.round_state != "HIDER_MOVE": return
        if self.mode=="ONLINE" and self.my_role!="HIDER": return
        delta = {'UP':(0,-1), 'DOWN':(0,1), 'LEFT':(-1,0), 'RIGHT':(1,0)}[d]
        self.action_move(delta)

    def on_skill(self, name):
        if self.round_state != "HIDER_MOVE": return
        if self.mode=="ONLINE" and self.my_role!="HIDER": return
        if self.h_used: return
        if self.h_cd > 0: return 
        self.action_skill(name)

    def on_radar(self):
        if self.round_state != "SEEKER_PROBE": return
        if self.mode=="ONLINE" and self.my_role!="SEEKER": return
        if self.s_cd==0 and not self.s_used: self.action_radar()

    def on_confirm(self):
        if self.round_state != "SEEKER_DRAW": return
        if self.mode=="ONLINE" and self.my_role!="SEEKER": return
        if len(self.path) > 1: self.action_catch()

    def on_map_tap(self, gx, gy):
        if self.round_state == "SEEKER_PROBE":
            if self.mode=="ONLINE" and self.my_role!="SEEKER": return
            self.action_probe(gx, gy)
        elif self.round_state == "SEEKER_DRAW":
            if self.mode=="ONLINE" and self.my_role!="SEEKER": return
            if (gx,gy) in self.walls or (gx,gy) not in self.visible: return
            last = self.path[-1]
            if abs(gx-last[0]) + abs(gy-last[1]) == 1:
                if (gx,gy) not in self.path: self.path.append((gx,gy))
                elif len(self.path)>1 and (gx,gy)==self.path[-2]: self.path.pop()
                if self.mode=="ONLINE": self.net.send({"t":"PATH", "p":self.path})

    def action_move(self, d):
        if self.mode=="ONLINE": self.net.send({"t":"MV","d":d})
        self._move(d)
    
    def _move(self, d):
        nx,ny = self.hider[0]+d[0], self.hider[1]+d[1]
        if not (0<=nx<31 and 0<=ny<31): return
        if (nx,ny) in self.walls and not self.h_phase: return
        if self.h_silent>0: self.h_silent-=1
        else: self.heat[self.hider[0]][self.hider[1]] = 5.0
        self.hider = [nx,ny]
        if self.h_phase: self.h_phase=False 
        
        if self.h_cd>0: self.h_cd-=1
        
        if self.h_decoy_t>0: self.h_decoy_t-=1
        else: self.h_decoy=None
        
        for x in range(31):
            for y in range(31): self.heat[x][y]*=0.75
            
        if self.hider==[15,15]: self.play('error'); self.over("Hider Wins!")
        else: self.round_state="SEEKER_PROBE"; self.h_used=False; self.radar=None; self.logs.append("Hider Moved")

    def action_skill(self, n):
        if self.mode=="ONLINE": self.net.send({"t":"SK","n":n})
        self._skill(n)
    
    def _skill(self, n):
        self.h_used=True
        if n=="PHASE": 
            self.h_phase=True; self.h_cd=6; self.logs.append("Skill: Phase")
        elif n=="DECOY":
            self.h_decoy=[min(30,max(0,self.hider[0]+random.randint(-1,1))), min(30,max(0,self.hider[1]+random.randint(-1,1)))]
            self.h_decoy_t=3; self.h_cd=4; self.logs.append("Skill: Decoy")
        elif n=="SILENT": 
            self.h_silent=3; self.h_cd=5; self.logs.append("Skill: Silent")

    def action_probe(self, x, y):
        if self.mode=="ONLINE": self.net.send({"t":"PR","p":[x,y]})
        self._probe(x,y)
    
    def _probe(self, x, y):
        target = self.h_decoy if (self.h_decoy and self.h_decoy_t>0) else self.hider
        d = abs(x-target[0]) + abs(y-target[1])
        if self.a_star(tuple(self.seeker), (x,y)) > 15: d += random.randint(-1,2)
        self.probes[(x,y)] = max(0,d); self.reveal([x,y], 2); self.play('ping')
        self.round_state="SEEKER_DRAW"; self.path=[tuple(self.seeker)]; self.logs.append(f"Probe ({x},{y}): {d}")
        if self.s_cd>0: self.s_cd-=1

    def action_radar(self):
        if self.mode=="ONLINE": self.net.send({"t":"RD"})
        self._radar()
    
    def _radar(self):
        hx,hy = self.hider
        ox,oy = max(0,hx-3+random.randint(-1,1)), max(0,hy-3+random.randint(-1,1))
        self.radar = (ox,oy,7,7); self.s_cd=3; self.s_used=True; self.logs.append("Radar Scanning")

    def action_catch(self):
        if self.mode=="ONLINE": self.net.send({"t":"CA","p":self.path})
        self._catch(self.path)
    
    def _catch(self, p):
        self.path = [tuple(x) for x in p]
        tgt = self.path[-1]
        if list(tgt) == self.hider:
            if len(self.path)-1 <= self.a_star(tuple(self.seeker), tuple(self.hider)):
                self.play('win'); self.over("Seeker Wins!")
            else: self.play('error'); self.logs.append("Escaped!"); self.teleport()
        else:
            self.seeker=list(tgt); self.reveal(self.seeker, 2); self.next_round()

    def teleport(self): self.hider=self.find_empty(); self.next_round()
    
    def next_round(self):
        self.turn+=1; self.path=[]; self.s_used=False
        if self.turn>self.max_turns: self.over("Timeout! Hider Wins")
        else: self.round_state="HIDER_MOVE"
    
    def over(self, t): self.msg=t; self.logs.append(t)

    def update_net(self):
        m = self.net.get_msg()
        if not m: return
        t = m.get("t")
        if t=="HELLO" and self.net.role=="HOST":
            s=random.randint(0,9999); self.net.send({"t":"INIT","s":s}); self.init_map(s); self.state="PLAYING"
        elif t=="INIT": self.init_map(m["s"]); self.state="PLAYING"
        elif t=="MV": self._move(m["d"])
        elif t=="SK": self._skill(m["n"])
        elif t=="PR": self._probe(m["p"][0], m["p"][1])
        elif t=="RD": self._radar()
        elif t=="PATH": self.path = [tuple(x) for x in m["p"]]
        elif t=="CA": self._catch(m["p"])

    def draw(self):
        self.screen.fill(C_BG)
        def draw_btn(btn):
            orig = btn.rect.copy()
            btn.rect.x *= self.scale; btn.rect.y *= self.scale
            btn.rect.w *= self.scale; btn.rect.h *= self.scale
            btn.draw(self.screen)
            btn.rect = orig

        if self.state == "MENU":
            t = self.font_big.render("SHADOW PATH", True, C_SEEKER)
            self.screen.blit(t, (self.win_w//2 - t.get_width()//2, 100*self.scale))
            for b in self.btns_menu: draw_btn(b)

        elif self.state == "LOBBY":
            t = self.font_big.render("Room: " + self.input_buf, True, C_SEEKER)
            self.screen.blit(t, (self.win_w//2 - t.get_width()//2, 100*self.scale))
            if self.net.role == "HOST":
                s = self.font.render("Waiting for player...", True, C_PATH)
                self.screen.blit(s, (self.win_w//2 - s.get_width()//2, 160*self.scale))
            else:
                for b in self.btns_lobby: draw_btn(b)
                for b in self.lobby_numpad: draw_btn(b)

        elif self.state == "PLAYING":
            grid_surf = pygame.Surface((MAP_PX, MAP_PX))
            grid_surf.fill(C_BG)
            for x in range(GRID_SIZE):
                for y in range(GRID_SIZE):
                    if (x,y) not in self.visible: continue
                    c = list(C_GRID)
                    if self.heat[x][y]>0.1: c[0] = min(255, c[0]+int(self.heat[x][y]*30))
                    if (x,y) in self.walls: c = C_WALL
                    if (x,y) in self.probes: c = [min(255, i+40) for i in c]
                    pygame.draw.rect(grid_surf, c, (x*(CELL_SIZE+1), y*(CELL_SIZE+1), CELL_SIZE, CELL_SIZE))
                    if (x,y) in self.probes:
                        t = self.font.render(str(self.probes[(x,y)]), True, (255,255,0))
                        grid_surf.blit(t, (x*(CELL_SIZE+1)+2, y*(CELL_SIZE+1)))
            
            if self.radar:
                r = self.radar
                pygame.draw.rect(grid_surf, (100,50,50), (r[0]*(CELL_SIZE+1), r[1]*(CELL_SIZE+1), r[2]*(CELL_SIZE+1), r[3]*(CELL_SIZE+1)), 2)
            
            if len(self.path)>1:
                pts = [(p[0]*(CELL_SIZE+1)+CELL_SIZE//2, p[1]*(CELL_SIZE+1)+CELL_SIZE//2) for p in self.path]
                pygame.draw.lines(grid_surf, C_PATH, False, pts, 2)

            sc = CELL_SIZE+1
            pygame.draw.circle(grid_surf, C_SEEKER, (self.seeker[0]*sc+8, self.seeker[1]*sc+8), 6)
            if self.mode=="LOCAL" or self.my_role=="HIDER" or self.msg:
                pygame.draw.circle(grid_surf, C_HIDER, (self.hider[0]*sc+8, self.hider[1]*sc+8), 6, 2)

            final_map = pygame.transform.scale(grid_surf, (int(MAP_PX*self.scale), int(MAP_PX*self.scale)))
            self.screen.blit(final_map, (self.offset_x, self.offset_y))
            
            info = f"Turn:{self.turn}  {self.round_state}"
            if self.mode=="ONLINE": info += f" ({'Seeker' if self.my_role=='SEEKER' else 'Hider'})"
            self.screen.blit(self.font.render(info, True, C_BTN_TEXT), (10, 10))
            if self.logs:
                l = self.font.render(self.logs[-1], True, (150,200,250))
                self.screen.blit(l, (10, 35))

            draw_btn(self.btn_back)
            
            # --- UI Visibility Logic ---
            if self.mode == "LOCAL":
                show_hider = (self.round_state == "HIDER_MOVE")
                show_seeker = not show_hider
            else:
                show_hider = (self.my_role == "HIDER")
                show_seeker = (self.my_role == "SEEKER")

            active_btns = []
            if show_hider:
                orig = self.dpad.x, self.dpad.y, self.dpad.size, self.dpad.btn_size
                self.dpad.x *= self.scale; self.dpad.y *= self.scale; self.dpad.size *= self.scale
                self.dpad.btn_size *= self.scale
                bs = self.dpad.btn_size
                self.dpad.rects = {
                    'UP': pygame.Rect(self.dpad.x + bs, self.dpad.y, bs, bs),
                    'DOWN': pygame.Rect(self.dpad.x + bs, self.dpad.y + bs*2, bs, bs),
                    'LEFT': pygame.Rect(self.dpad.x, self.dpad.y + bs, bs, bs),
                    'RIGHT': pygame.Rect(self.dpad.x + bs*2, self.dpad.y + bs, bs, bs)
                }
                self.dpad.draw(self.screen)
                self.dpad.x, self.dpad.y, self.dpad.size, self.dpad.btn_size = orig
                self.dpad.rects = { 
                    'UP': pygame.Rect(orig[0] + orig[3], orig[1], orig[3], orig[3]),
                    'DOWN': pygame.Rect(orig[0] + orig[3], orig[1] + orig[3]*2, orig[3], orig[3]),
                    'LEFT': pygame.Rect(orig[0], orig[1] + orig[3], orig[3], orig[3]),
                    'RIGHT': pygame.Rect(orig[0] + orig[3]*2, orig[1] + orig[3], orig[3], orig[3])
                }

                draw_btn(self.btn_skill_q)
                draw_btn(self.btn_skill_1)
                draw_btn(self.btn_skill_2)
                active_btns += [self.btn_skill_q, self.btn_skill_1, self.btn_skill_2]

            if show_seeker:
                draw_btn(self.btn_radar)
                draw_btn(self.btn_confirm)
                active_btns += [self.btn_radar, self.btn_confirm]

            # --- Tooltip Drawing ---
            tooltip = None
            for b in active_btns:
                if b.clicked and (time.time() - b.press_start > 0.5):
                    tooltip = b.desc
            
            if tooltip:
                txt = self.font.render(tooltip, True, (255, 255, 255))
                w, h = txt.get_width() + 20, txt.get_height() + 20
                rect = pygame.Rect((self.win_w - w)//2, (self.win_h - h)//2, w, h)
                pygame.draw.rect(self.screen, (0, 0, 0, 200), rect, 0, 10)
                pygame.draw.rect(self.screen, C_SEEKER, rect, 2, 10)
                self.screen.blit(txt, (rect.x + 10, rect.y + 10))

            if self.msg:
                ov = pygame.Surface((self.win_w, self.win_h), pygame.SRCALPHA)
                ov.fill((0,0,0,200))
                self.screen.blit(ov, (0,0))
                t = self.font_big.render(self.msg, True, C_HIDER)
                self.screen.blit(t, (self.win_w//2-t.get_width()//2, self.win_h//2))

        pygame.display.flip()

    def run(self):
        while True:
            if self.mode=="ONLINE": self.update_net()
            events = pygame.event.get()
            for e in events:
                if e.type == pygame.QUIT: self.quit_game()
                
                pos = None
                if e.type == pygame.MOUSEBUTTONDOWN: pos = e.pos
                elif e.type == pygame.MOUSEBUTTONUP: pos = e.pos
                
                if pos:
                    lx, ly = pos[0] / self.scale, pos[1] / self.scale
                    
                    if self.state == "MENU":
                        if e.type == pygame.MOUSEBUTTONDOWN:
                            for b in self.btns_menu: b.check_down((lx, ly))
                        elif e.type == pygame.MOUSEBUTTONUP:
                            for b in self.btns_menu: b.check_up((lx, ly))
                    
                    elif self.state == "LOBBY":
                        btns = self.btns_lobby + self.lobby_numpad
                        if e.type == pygame.MOUSEBUTTONDOWN:
                            for b in btns: b.check_down((lx, ly))
                        elif e.type == pygame.MOUSEBUTTONUP:
                            for b in btns: b.check_up((lx, ly))
                    
                    elif self.state == "PLAYING":
                        ui_hit = False
                        all_btns = [self.btn_back]
                        
                        # Logic matches draw()
                        if self.mode == "LOCAL":
                            is_hider_turn = (self.round_state == "HIDER_MOVE")
                            allow_hider = is_hider_turn
                            allow_seeker = not is_hider_turn
                        else:
                            allow_hider = (self.my_role == "HIDER")
                            allow_seeker = (self.my_role == "SEEKER")

                        if allow_hider:
                            all_btns += [self.btn_skill_q, self.btn_skill_1, self.btn_skill_2]
                            if e.type == pygame.MOUSEBUTTONDOWN:
                                if self.dpad.check_down((lx,ly)): ui_hit = True
                            elif e.type == pygame.MOUSEBUTTONUP:
                                self.dpad.check_up((lx,ly))
                        
                        if allow_seeker:
                            all_btns += [self.btn_radar, self.btn_confirm]

                        if e.type == pygame.MOUSEBUTTONDOWN:
                            for b in all_btns: 
                                if b.check_down((lx,ly)): ui_hit = True
                        elif e.type == pygame.MOUSEBUTTONUP:
                            for b in all_btns: b.check_up((lx,ly))

                        if not ui_hit and e.type == pygame.MOUSEBUTTONDOWN:
                            map_scr_x, map_scr_y = self.offset_x, self.offset_y
                            if map_scr_x <= pos[0] <= map_scr_x + MAP_PX*self.scale and \
                               map_scr_y <= pos[1] <= map_scr_y + MAP_PX*self.scale:
                                
                                rel_x = (pos[0] - map_scr_x) / self.scale
                                rel_y = (pos[1] - map_scr_y) / self.scale
                                
                                gx = int(rel_x // (CELL_SIZE+1))
                                gy = int(rel_y // (CELL_SIZE+1))
                                if 0<=gx<GRID_SIZE and 0<=gy<GRID_SIZE:
                                    self.on_map_tap(gx, gy)
                
                if self.msg and e.type == pygame.MOUSEBUTTONDOWN:
                    self.set_state("MENU"); self.msg=""

            self.draw()
            self.clock.tick(30)

if __name__ == "__main__": ShadowMobile().run()