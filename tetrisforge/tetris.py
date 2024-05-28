import base64
import ctypes
import os
import random
import socket
import subprocess
import sys
import threading
import time
import struct
import traceback
from typing import override

import requests
from PySide6.QtCore import QBasicTimer, Qt, QTimer, Signal, Slot
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListWidget,
    QMainWindow,
    QPushButton,
    QStatusBar,
    QVBoxLayout,
    QWidget,
)

def ipv4_port_to_base64(ipv4: str, port: int) -> str:
    octets = ipv4.split('.')
    ip_bytes = struct.pack('!BBBB', int(octets[0]), int(octets[1]), int(octets[2]), int(octets[3]))
    port_bytes = struct.pack('!H', port)
    combined_bytes = ip_bytes + port_bytes
    base64_encoded = base64.b64encode(combined_bytes).decode('utf-8')
    return base64_encoded

def base64_to_ipv4_port(base64_encoded: str) -> (str, int):
    combined_bytes = base64.b64decode(base64_encoded)
    ip_bytes = combined_bytes[:4]
    octets = struct.unpack('!BBBB', ip_bytes)
    ipv4 = '.'.join(map(str, octets))
    port_bytes = combined_bytes[4:]
    port = struct.unpack('!H', port_bytes)[0]
    return ipv4, port

class Tetris(QMainWindow):
    """
    Main application window for the Tetris game.
    """

    board_width = 10
    BoardHeight = 22
    Speed = 300

    def __init__(self):
        """
        Initialize the Tetris game window.
        """
        super().__init__()
        self.init_ui()
        self.lobby: Lobby
        self.main_menu: MainMenu
        self.statusbar: QStatusBar
        self.tboard: Board

    def init_ui(self):
        """
        Initialize the user interface elements.
        """
        self.main_menu = MainMenu(self, game=self)
        self.setCentralWidget(self.main_menu)
        self.statusbar = self.statusBar()

        self.resize(600, 800)
        self.center()
        self.setWindowTitle("Tetris")
        self.show()

    def center(self):
        """
        Center the Tetris game window on the screen.
        """
        screen = self.screen().geometry()
        size = self.geometry()
        self.move(
            (screen.width() - size.width()) // 2, (screen.height() - size.height()) // 2
        )

    @Slot(bool, bool)
    def start_game_from_network(self, multiplayer, is_host):
        print("Starting game from network...")
        self.start_game(
            multiplayer=multiplayer, is_host=is_host, join_code=self.lobby.join_code
        )

    def start_game(self, multiplayer=False, is_host=False, join_code=""):
        """
        Start the game.
        """
        print(
            f"Starting game: multiplayer={multiplayer}, is_host={is_host}, join_code={join_code}"
        )
        self.tboard = Board(
            self,
            game=self,
            multiplayer=multiplayer,
            is_host=is_host,
            join_code=join_code,
        )
        self.setCentralWidget(self.tboard)
        self.tboard.msg2Statusbar.connect(self.statusbar.showMessage)
        self.tboard.start()

        if multiplayer:
            self.resize(800, 800)  # Increase window width for multiplayer

        # Ensure the window gains focus
        self.raise_()
        self.activateWindow()

        # Set focus on the game board to ensure key presses are registered
        self.tboard.setFocus()

    def show_game_over(self, message):
        """
        Show a game over message.
        """
        self.statusbar.showMessage(message)
        self.tboard.timer.stop()
        self.tboard.finalize_timer.stop()
        self.tboard.is_started = False
        self.tboard.update()


class MainMenu(QWidget):
    """
    Main menu for Tetris game.
    """

    def __init__(self, parent, game: Tetris):
        super().__init__(parent)
        self.game: Tetris = game
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout()

        solo_button = QPushButton("Solo")
        solo_button.clicked.connect(self.start_solo)
        layout.addWidget(solo_button)

        host_button = QPushButton("Host Multiplayer")
        host_button.clicked.connect(self.host_multiplayer)
        layout.addWidget(host_button)

        join_button = QPushButton("Join Multiplayer")
        join_button.clicked.connect(self.join_multiplayer)
        layout.addWidget(join_button)

        self.setLayout(layout)

    def start_solo(self):
        self.game.start_game(multiplayer=False, is_host=False)

    def host_multiplayer(self):
        self.game.lobby = Lobby(self.parent(), game=self.game, is_host=True)
        self.game.setCentralWidget(self.game.lobby)

    def join_multiplayer(self):
        join_code, ok = QInputDialog.getText(
            self, "Join Multiplayer", "Enter join code:"
        )
        if ok and join_code:
            self.game.lobby = Lobby(
                self.parent(), game=self.game, is_host=False, join_code=join_code
            )
            self.game.setCentralWidget(self.game.lobby)


class Lobby(QWidget):
    """
    Lobby for Tetris multiplayer game.
    """

    def __init__(self, parent, game: Tetris, is_host=False, join_code=""):
        super().__init__(parent)
        self.game: Tetris = game
        self.is_host: bool = is_host
        self.join_code: str = join_code
        self.init_ui()
        self.players = []
        self.players_list: QListWidget
        self.start_button: QPushButton
        self.server_socket: socket.socket
        self.server_port: int
        self.server_thread: threading.Thread
        self.client_socket: socket.socket
        self.client_thread: threading.Thread

        if self.is_host:
            self.setup_host()
        else:
            self.setup_client()

    def init_ui(self):
        layout = QVBoxLayout()

        self.players_list = QListWidget()
        layout.addWidget(self.players_list)

        if self.is_host:
            self.start_button = QPushButton("Start Game")
            self.start_button.clicked.connect(self.start_game)
            layout.addWidget(self.start_button)

        self.setLayout(layout)

    def setup_host(self):
        self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_socket.bind(("0.0.0.0", 0))  # Bind to any available port
        self.server_socket.listen(5)
        self.server_port = self.server_socket.getsockname()[1]
        if not self.is_admin():
            self.run_as_admin()
        else:
            self.allow_firewall_access(self.server_port)  # Add firewall rule
        self.server_thread = threading.Thread(
            target=self.server_thread_func, daemon=True
        )
        self.server_thread.start()
        host_ip = self.get_external_ip()
        self.join_code = ipv4_port_to_base64(host_ip, self.server_port)
        loopback_code = ipv4_port_to_base64("127.0.0.1", self.server_port)
        print(f"Join code: {self.join_code}")
        print(f"Loopback code: {loopback_code}")

    def is_admin(self):
        try:
            return ctypes.windll.shell32.IsUserAnAdmin()
        except Exception as e:
            print(f"Admin check failed: {e}")
            return False

    def run_as_admin(self):
        script = os.path.abspath(sys.argv[0])
        params = " ".join([script] + sys.argv[1:])
        try:
            ctypes.windll.shell32.ShellExecuteW(
                None, "runas", sys.executable, params, None, 1
            )
        except Exception as e:
            print(f"Failed to elevate privileges: {e}")
        sys.exit(0)

    def get_external_ip(self):
        # This method retrieves the external IP address of the server
        try:
            response = requests.get("https://api.ipify.org?format=text", timeout=10)
            if response.status_code == 200:
                return response.text
            else:
                return "127.0.0.1"
        except Exception:
            return "127.0.0.1"

    def allow_firewall_access(self, port):
        if os.name == "nt":  # Only for Windows
            rule_name = f"Tetris_Server_Port_{port}"
            try:
                subprocess.check_call(
                    [
                        "netsh",
                        "advfirewall",
                        "firewall",
                        "add",
                        "rule",
                        f"name={rule_name}",
                        "dir=in",
                        "action=allow",
                        "protocol=TCP",
                        f"localport={port}",
                    ]
                )
                print(f"Firewall rule added for port {port}")
            except subprocess.CalledProcessError as e:
                print(f"Failed to add firewall rule: {e}")

    def setup_client(self):
        host, port = base64_to_ipv4_port(self.join_code)
        print(f"Connecting to server at {host}:{port}")
        self.client_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            self.client_socket.connect((host, int(port)))
            self.client_thread = threading.Thread(
                target=self.client_thread_func, daemon=True
            )
            self.client_thread.start()
        except ConnectionRefusedError as e:
            print(f"Connection refused: {e}")
        except Exception as e:
            print(f"Failed to connect: {e}")

    def server_thread_func(self):
        while True:
            try:
                client_socket, addr = self.server_socket.accept()
                self.players.append(client_socket)
                print(f"Accepted connection from {addr}")
                self.add_player(f"Player {len(self.players)}")
                threading.Thread(
                    target=self.network_loop, args=(client_socket,), daemon=True
                ).start()
            except Exception as e:
                print(f"Server thread error: {e}")
                traceback.print_exc()

    def client_thread_func(self):
        try:
            self.network_loop(self.client_socket)
        except Exception as e:
            print(f"Client thread error: {e}")
            traceback.print_exc()

    def network_loop(self, sock):
        while True:
            try:
                data = sock.recv(1024).decode("utf-8")
                if data:
                    print(f"Received data: {data}")
                    if data == "start_game":
                        print("Received start_game command")
                        self.game.start_game_from_network(True, False)
            except Exception as e:
                print(f"Network loop error: {e}")
                traceback.print_exc()
                break

    @Slot(str)
    def add_player(self, player_name):
        self.players_list.addItem(player_name)

    def start_game(self):
        for player in self.players:
            try:
                print("Sending start_game to player")
                player.send("start_game".encode("utf-8"))
            except Exception as e:
                print(f"Error sending start_game: {e}")
                traceback.print_exc()
        self.game.start_game(multiplayer=True, is_host=True, join_code=self.join_code)


class Board(QFrame):
    """
    Main game board for Tetris.
    """

    msg2Statusbar = Signal(str)

    board_width = 10
    BoardHeight = 22
    Speed = 300
    FinalizeDelay = 1000  # Delay in milliseconds
    KeyRepeatDelay = 150  # Delay for repeating key actions

    def __init__(self, parent, game, multiplayer=False, is_host=False, join_code=""):
        """
        Initialize the game board.
        """
        super().__init__(parent)
        self.game: Tetris = game
        self.multiplayer = multiplayer
        self.is_host = is_host
        self.join_code = join_code
        self.init_board()
        self.timer: QBasicTimer
        self.finalize_timer: QTimer
        self.is_waiting_after_line: bool
        self.cur_x: int
        self.cur_y: int
        self.num_lines_removed: int
        self.board: list
        self.is_started: bool
        self.is_paused: bool
        self.bag: list
        self.next_piece: Shape
        self.hold_piece: Shape
        self.current_piece: Shape
        self.hold_used: bool
        self.hold_locked: bool
        self.is_landed: bool
        self.left_key_timer: QTimer
        self.right_key_timer: QTimer
        self.down_key_timer: QTimer
        self.goal: int
        self.num_goals_reached: int
        self.lines_to_goal: int
        self.next_piece_label: QLabel
        self.hold_piece_label: QLabel
        self.goal_label: QLabel
        self.level_label: QLabel
        self.lines_to_goal_label: QLabel
        self.score_label: QLabel
        self.other_boards: list
        self.other_boards_layout: QVBoxLayout
        self.other_boards_widget: QWidget
        self.main_layout: QHBoxLayout
        self.server_socket: socket.socket
        self.server_port: int
        self.server_thread: threading.Thread
        self.client_socket: socket.socket
        self.client_thread: threading.Thread
        self.small_board: SmallBoard

    def init_board(self):
        """
        Initialize the board settings and state.
        """
        self.timer = QBasicTimer()
        self.finalize_timer = QTimer(self)
        self.finalize_timer.timeout.connect(self.finalize_piece)
        self.is_waiting_after_line = False
        self.cur_x = 0
        self.cur_y = 0
        self.num_lines_removed = 0
        self.board = []

        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.is_started = False
        self.is_paused = False
        self.clear_board()

        self.bag = []
        self.next_piece = Shape()
        self.next_piece.set_shape(self.get_next_shape())
        self.hold_piece = Shape()
        self.current_piece = Shape()
        self.hold_used = False
        self.hold_locked = False
        self.is_landed = False

        # Timers for key repeats
        self.left_key_timer = QTimer(self)
        self.right_key_timer = QTimer(self)
        self.down_key_timer = QTimer(self)

        self.left_key_timer.timeout.connect(self.move_left)
        self.right_key_timer.timeout.connect(self.move_right)
        self.down_key_timer.timeout.connect(self.move_down)

        self.goal = 10
        self.num_goals_reached = 0

        self.lines_to_goal = 0
        self.next_piece_label = QLabel(self)
        self.hold_piece_label = QLabel(self)
        self.goal_label = QLabel(self)
        self.level_label = QLabel(self)
        self.lines_to_goal_label = QLabel(self)
        self.score_label = QLabel(self)

        if self.multiplayer:
            self.other_boards = []
            self.other_boards_layout = QVBoxLayout()
            self.other_boards_widget = QWidget(self)
            self.other_boards_widget.setLayout(self.other_boards_layout)

            self.main_layout = QHBoxLayout(self)
            self.main_layout.addWidget(self.other_boards_widget)
            self.main_layout.addWidget(self)
            self.setLayout(self.main_layout)  # Moved after the widget setup

            if self.is_host:
                self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                self.server_socket.bind(("0.0.0.0", 0))  # Bind to any available port
                self.server_socket.listen(5)
                self.server_port = self.server_socket.getsockname()[1]
                if not self.is_admin():
                    self.run_as_admin()
                else:
                    self.allow_firewall_access(self.server_port)  # Add firewall rule
                self.server_thread = threading.Thread(
                    target=self.server_thread_func, daemon=True
                )
                self.server_thread.start()
                host_ip = self.get_external_ip()
                join_code = ipv4_port_to_base64(host_ip, self.server_port)
                print(f"Join code: {join_code}")
            else:
                self.client_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                host, port = base64_to_ipv4_port(self.join_code)
                print(f"Connecting to server at {host}:{port}")
                try:
                    self.client_socket.connect((host, int(port)))
                    self.client_thread = threading.Thread(
                        target=self.client_thread_func, daemon=True
                    )
                    self.client_thread.start()
                except ConnectionRefusedError as e:
                    print(f"Connection refused: {e}")
                except Exception as e:
                    print(f"Failed to connect: {e}")

    def is_admin(self):
        try:
            return ctypes.windll.shell32.IsUserAnAdmin()
        except Exception as e:
            print(f"Admin check failed: {e}")
            return False

    def run_as_admin(self):
        script = os.path.abspath(sys.argv[0])
        params = " ".join([script] + sys.argv[1:])
        try:
            ctypes.windll.shell32.ShellExecuteW(
                None, "runas", sys.executable, params, None, 1
            )
        except Exception as e:
            print(f"Failed to elevate privileges: {e}")
        sys.exit(0)

    def get_external_ip(self):
        # This method retrieves the external IP address of the server
        try:
            response = requests.get("https://api.ipify.org?format=text")
            if response.status_code == 200:
                return response.text
            else:
                return "127.0.0.1"
        except Exception:
            return "127.0.0.1"

    def allow_firewall_access(self, port):
        if os.name == "nt":  # Only for Windows
            rule_name = f"Tetris_Server_Port_{port}"
            try:
                subprocess.check_call(
                    [
                        "netsh",
                        "advfirewall",
                        "firewall",
                        "add",
                        "rule",
                        f"name={rule_name}",
                        "dir=in",
                        "action=allow",
                        "protocol=TCP",
                        f"localport={port}",
                    ]
                )
                print(f"Firewall rule added for port {port}")
            except subprocess.CalledProcessError as e:
                print(f"Failed to add firewall rule: {e}")

    def server_thread_func(self):
        while True:
            try:
                client_socket, addr = self.server_socket.accept()
                self.small_board = SmallBoard(self.other_boards_widget)
                self.other_boards.append(self.small_board)
                self.other_boards_layout.addWidget(self.small_board)
                print(f"Accepted connection from {addr}")
                threading.Thread(
                    target=self.network_loop, args=(client_socket,), daemon=True
                ).start()
            except Exception as e:
                print(f"Server thread error: {e}")
                traceback.print_exc()

    def client_thread_func(self):
        try:
            self.network_loop(self.client_socket)
        except Exception as e:
            print(f"Client thread error: {e}")
            traceback.print_exc()

    def network_loop(self, sock):
        while True:
            try:
                data = sock.recv(1024).decode("utf-8")
                if data:
                    print(f"Received data: {data}")
                    if data.startswith("board_state"):
                        board_index, board_state = data.split(":")[1:]
                        board_index = int(board_index)
                        board_state = list(map(int, board_state.split(",")))
                        self.small_board.update_board(board_state)
                    elif data == "game_over":
                        self.game.show_game_over("You Lost!")
            except Exception as e:
                print(f"Network loop error: {e}")
                traceback.print_exc()
                break

    def start(self):
        """
        Start the game.
        """
        print("Starting the game...")
        if self.is_paused:
            return

        self.is_started = True
        self.is_waiting_after_line = False
        self.num_lines_removed = 0
        self.clear_board()

        self.msg2Statusbar.emit(str(self.num_lines_removed))

        self.new_piece()
        self.timer.start(Board.Speed, self)

    def pause(self):
        """
        Pause the game.
        """
        if not self.is_started:
            return

        self.is_paused = not self.is_paused

        if self.is_paused:
            self.timer.stop()
            self.finalize_timer.stop()
            self.left_key_timer.stop()
            self.right_key_timer.stop()
            self.down_key_timer.stop()
            self.msg2Statusbar.emit("Paused")
        else:
            self.timer.start(Board.Speed, self)
            self.msg2Statusbar.emit(str(self.num_lines_removed))

        self.update()

    @override
    def paintEvent(self, event):  # type: ignore
        """
        Handle the paint event to draw the board and pieces.
        """
        painter = QPainter(self)
        rect = self.contentsRect()

        board_top = rect.bottom() - Board.BoardHeight * self.square_size()
        self.draw_background_grid(painter)

        for i in range(Board.BoardHeight):
            for j in range(Board.board_width):
                shape = self.shape_at(j, Board.BoardHeight - i - 1)

                if shape != Tetrominoe.NoShape:
                    self.draw_square(
                        painter,
                        rect.left() + j * self.square_size(),
                        board_top + i * self.square_size(),
                        shape,
                    )

        if self.current_piece.shape() != Tetrominoe.NoShape:
            for i in range(4):
                x = self.cur_x + self.current_piece.x(i)
                y = self.cur_y - self.current_piece.y(i)
                self.draw_square(
                    painter,
                    rect.left() + x * self.square_size(),
                    board_top + (Board.BoardHeight - y - 1) * self.square_size(),
                    self.current_piece.shape(),
                )

        self.draw_next_piece(painter)
        self.draw_hold_piece(painter)
        self.labels()

    def draw_background_grid(self, painter):
        """
        Draw the grid background for the board.
        """
        painter.setPen(QPen(QColor(80, 80, 80), 1, Qt.PenStyle.SolidLine))
        rect = self.contentsRect()
        board_top = rect.bottom() - Board.BoardHeight * self.square_size()

        for i in range(Board.board_width + 1):
            x = rect.left() + i * self.square_size()
            painter.drawLine(x, board_top, x, rect.bottom())

        for i in range(Board.BoardHeight + 1):
            y = board_top + i * self.square_size()
            painter.drawLine(
                rect.left(), y, rect.left() + Board.board_width * self.square_size(), y
            )

    @override
    def keyPressEvent(self, event):
        """
        Handle key press events for game controls.
        """
        if not self.is_started or self.current_piece.shape() == Tetrominoe.NoShape:
            super(Board, self).keyPressEvent(event)
            return

        key = event.key()

        if key == Qt.Key.Key_P:
            self.pause()
            return

        if self.is_paused:
            return

        elif key == Qt.Key.Key_Left:
            self.move_left()
            self.left_key_timer.start(Board.KeyRepeatDelay)

        elif key == Qt.Key.Key_Right:
            self.move_right()
            self.right_key_timer.start(Board.KeyRepeatDelay)

        elif key == Qt.Key.Key_Down:
            self.move_down()
            self.down_key_timer.start(Board.KeyRepeatDelay)

        elif key == Qt.Key.Key_Space:
            self.drop_down()

        elif key == Qt.Key.Key_Up:
            self.try_rotate_right()
            if self.finalize_timer.isActive():
                self.finalize_timer.start(Board.FinalizeDelay)

        elif key == Qt.Key.Key_C:
            self.hold_current_piece()

        else:
            super(Board, self).keyPressEvent(event)

    @override
    def keyReleaseEvent(self, event):
        """
        Handle key release events for stopping key repeats.
        """
        key = event.key()

        if key == Qt.Key.Key_Left:
            self.left_key_timer.stop()
        elif key == Qt.Key.Key_Right:
            self.right_key_timer.stop()
        elif key == Qt.Key.Key_Down:
            self.down_key_timer.stop()

    def move_left(self):
        """
        Move the current piece left.
        """
        self.try_move(self.current_piece, self.cur_x - 1, self.cur_y)

    def move_right(self):
        """
        Move the current piece right.
        """
        self.try_move(self.current_piece, self.cur_x + 1, self.cur_y)

    def move_down(self):
        """
        Move the current piece down.
        """
        if not self.try_move(self.current_piece, self.cur_x, self.cur_y - 1):
            self.piece_dropped()

    @override
    def timerEvent(self, event):
        """
        Handle timer events for game updates.
        """
        if event.timerId() == self.timer.timerId():
            if self.is_waiting_after_line:
                self.is_waiting_after_line = False
                self.new_piece()
            else:
                self.one_line_down()
        else:
            super(Board, self).timerEvent(event)

    def clear_board(self):
        """
        Clear the game board.
        """
        self.board = [Tetrominoe.NoShape] * (Board.BoardHeight * Board.board_width)

    def drop_down(self):
        """
        Drop the current piece to the bottom.
        """
        new_y = self.cur_y
        while new_y > 0:
            if not self.try_move(self.current_piece, self.cur_x, new_y - 1):
                break
            new_y -= 1
        self.piece_dropped()

    def one_line_down(self):
        """
        Move the current piece one line down.
        """
        if not self.try_move(self.current_piece, self.cur_x, self.cur_y - 1):
            self.piece_dropped()

    def piece_dropped(self):
        """
        Finalize the placement of the current piece.
        """
        self.is_landed = True
        self.finalize_piece()

    def finalize_piece(self):
        """
        Finalize the placement of the current piece after it has landed.
        """
        self.finalize_timer.stop()
        for i in range(4):
            x = self.cur_x + self.current_piece.x(i)
            y = self.cur_y - self.current_piece.y(i)
            self.set_shape_at(x, y, self.current_piece.shape())

        self.remove_full_lines()
        self.is_landed = False

        if not self.is_waiting_after_line:
            self.new_piece()
            self.hold_locked = False

    def remove_full_lines(self):
        """
        Remove all full lines from the board and update the score.
        """
        num_full_lines = 0
        rows_to_remove = []

        for i in range(Board.BoardHeight):
            n = 0
            for j in range(Board.board_width):
                if not self.shape_at(j, i) == Tetrominoe.NoShape:
                    n += 1

            if n == 10:
                rows_to_remove.append(i)

        rows_to_remove.reverse()

        for m in rows_to_remove:
            for k in range(m, Board.BoardHeight - 1):
                for l in range(Board.board_width):
                    self.set_shape_at(l, k, self.shape_at(l, k + 1))
            for l in range(Board.board_width):
                self.set_shape_at(l, Board.BoardHeight - 1, Tetrominoe.NoShape)

        num_full_lines += len(rows_to_remove)

        if num_full_lines > 0:
            self.num_lines_removed += len(rows_to_remove)
            self.msg2Statusbar.emit(str(self.num_lines_removed))
            self.is_waiting_after_line = True
            self.current_piece.set_shape(Tetrominoe.NoShape)
            self.update()
            self.lines_to_goal += len(rows_to_remove)
            # Update the speed based on goals reached
            if self.lines_to_goal >= self.goal:
                if self.num_goals_reached != 0:
                    self.goal = (5 * self.num_goals_reached) + self.goal
                else:
                    self.goal = 5 + self.goal
                self.lines_to_goal = 0
                self.num_goals_reached += 1
                Board.Speed -= Board.Speed / 4
                self.timer.start(int(Board.Speed), self)
                self.labels()

    def new_piece(self):
        """
        Create a new piece and set it as the current piece.
        """
        self.current_piece.set_shape(self.next_piece.shape())
        self.next_piece.set_shape(self.get_next_shape())
        self.cur_x = Board.board_width // 2 + 1
        self.cur_y = Board.BoardHeight - 1 + self.current_piece.min_y()

        if not self.try_move(self.current_piece, self.cur_x, self.cur_y):
            self.current_piece.set_shape(Tetrominoe.NoShape)
            self.timer.stop()
            self.finalize_timer.stop()
            self.is_started = False
            self.msg2Statusbar.emit("Game over")

    def hold_current_piece(self):
        """
        Hold the current piece, swapping with the held piece if any.
        """
        if not self.hold_locked:
            if self.hold_piece.shape() == Tetrominoe.NoShape:
                self.hold_piece.set_shape(self.current_piece.shape())
                self.new_piece()
            else:
                self.current_piece, self.hold_piece = (
                    self.hold_piece,
                    self.current_piece,
                )
                self.cur_x = Board.board_width // 2 + 1
                self.cur_y = Board.BoardHeight - 1 + self.current_piece.min_y()
                if not self.try_move(self.current_piece, self.cur_x, self.cur_y):
                    self.current_piece.set_shape(Tetrominoe.NoShape)
                    self.timer.stop()
                    self.finalize_timer.stop()
                    self.is_started = False
                    self.msg2Statusbar.emit("Game over")
            self.hold_locked = True
            self.update()

    def try_move(self, new_piece, new_x, new_y):
        """
        Try to move the current piece to a new position.
        """
        for i in range(4):
            x = new_x + new_piece.x(i)
            y = new_y - new_piece.y(i)
            if x < 0 or x >= Board.board_width or y < 0 or y >= Board.BoardHeight:
                return False
            if self.shape_at(x, y) != Tetrominoe.NoShape:
                return False

        self.current_piece = new_piece
        self.cur_x = new_x
        self.cur_y = new_y
        self.update()
        return True

    def try_rotate_right(self):
        """
        Try to rotate the current piece to the right.
        """
        new_piece = self.current_piece.rotate_right()
        if self.try_move(new_piece, self.cur_x, self.cur_y):
            return
        # Try to move piece left, right, up, and down to allow rotation
        if self.try_move(new_piece, self.cur_x - 1, self.cur_y):
            return
        if self.try_move(new_piece, self.cur_x + 1, self.cur_y):
            return
        if self.try_move(new_piece, self.cur_x, self.cur_y + 1):
            return
        if self.try_move(new_piece, self.cur_x, self.cur_y - 1):
            return

    def get_next_shape(self):
        """
        Get the next shape from the bag.
        """
        if not self.bag:
            self.bag = list(range(1, 8))
            random.shuffle(self.bag)
        return self.bag.pop()

    def draw_square(self, painter, x, y, shape):
        """
        Draw a square for a piece on the board.
        """
        colors = [
            QColor(169, 169, 169),  # NoShape - Dark Gray
            QColor(255, 69, 69),  # ZShape - Medium Red
            QColor(60, 179, 113),  # SShape - Medium Green
            QColor(64, 224, 208),  # LineShape - Medium Cyan
            QColor(186, 85, 211),  # TShape - Medium Purple
            QColor(255, 255, 102),  # SquareShape - Medium Yellow
            QColor(255, 140, 0),  # LShape - Medium Orange
            QColor(30, 144, 255),  # MirroredLShape - Medium Blue
        ]

        color = colors[shape]

        painter.fillRect(
            x + 1, y + 1, self.square_size() - 2, self.square_size() - 2, color
        )

        painter.setPen(color.lighter())
        painter.drawLine(x, y + self.square_size() - 1, x, y)
        painter.drawLine(x, y, x + self.square_size() - 1, y)

        painter.setPen(color.darker())
        painter.drawLine(
            x + 1,
            y + self.square_size() - 1,
            x + self.square_size() - 1,
            y + self.square_size() - 1,
        )
        painter.drawLine(
            x + self.square_size() - 1,
            y + self.square_size() - 1,
            x + self.square_size() - 1,
            y + 1,
        )

    def draw_next_piece(self, painter):
        """
        Draw the next piece preview.
        """
        self.next_piece_label.setText("Next Piece:")
        self.next_piece_label.setGeometry(
            self.contentsRect().right() - 200, 20, 150, 30
        )
        self.next_piece_label.show()

        for i in range(4):
            x = 1 + self.next_piece.x(i)
            y = 1 + self.next_piece.y(i)
            self.draw_square(
                painter,
                self.contentsRect().right() - 170 + x * self.square_size(),
                60 + y * self.square_size(),
                self.next_piece.shape(),
            )

    def draw_hold_piece(self, painter):
        """
        Draw the held piece preview.
        """
        self.hold_piece_label.setText("Hold Piece:")
        self.hold_piece_label.setGeometry(
            self.contentsRect().right() - 200, 200, 150, 30
        )
        self.hold_piece_label.show()

        if self.hold_piece.shape() != Tetrominoe.NoShape:
            for i in range(4):
                x = 1 + self.hold_piece.x(i)
                y = 1 + self.hold_piece.y(i)
                self.draw_square(
                    painter,
                    self.contentsRect().right() - 170 + x * self.square_size(),
                    240 + y * self.square_size(),
                    self.hold_piece.shape(),
                )

    def labels(self):
        """
        Update and display game statistics labels.
        """
        font = QFont("SansSerif", 14, QFont.Weight.Bold)

        self.goal_label.setFont(font)
        self.level_label.setFont(font)
        self.lines_to_goal_label.setFont(font)
        self.score_label.setFont(font)
        self.goal_label.setText(f"Goal: {self.goal}")
        self.level_label.setText(f"Level: {self.num_goals_reached + 1}")
        difference = int(self.goal) - int(self.lines_to_goal)
        self.lines_to_goal_label.setText(f"Lines to goal: {difference}")
        self.score_label.setText(f"Score: {self.num_lines_removed * 1000}")
        self.goal_label.setGeometry(self.contentsRect().right() - 200, 400, 150, 30)
        self.level_label.setGeometry(self.contentsRect().right() - 200, 430, 150, 30)
        self.lines_to_goal_label.setGeometry(
            self.contentsRect().right() - 200, 460, 210, 30
        )
        self.score_label.setGeometry(self.contentsRect().right() - 200, 490, 150, 30)
        self.goal_label.show()
        self.level_label.show()
        self.lines_to_goal_label.show()
        self.score_label.show()

    def shape_at(self, x, y):
        """
        Return the shape at the given board coordinates.
        """
        return self.board[(y * Board.board_width) + x]

    def set_shape_at(self, x, y, shape):
        """
        Set the shape at the given board coordinates.
        """
        self.board[(y * Board.board_width) + x] = shape

    def square_size(self):
        """
        Return the size of one square on the board.
        """
        rect = self.contentsRect()
        board_width = rect.width() * 2 // 3  # Two-thirds of the width for the board
        square_width = board_width // Board.board_width
        square_height = rect.height() // Board.BoardHeight
        return min(square_width, square_height)


class SmallBoard(QWidget):
    """
    Smaller representation of the game board for other players in multiplayer.
    """

    def __init__(self, parent):
        super().__init__(parent)
        self.board = []

        self.setFixedSize(100, 220)  # Set size for small board
        self.clear_board()

    def clear_board(self):
        self.board = [Tetrominoe.NoShape] * (Board.BoardHeight * Board.board_width)

    @Slot(list)
    def update_board(self, board_state):
        self.board = board_state
        self.update()

    @override
    def paintEvent(self, event):
        painter = QPainter(self)
        rect = self.contentsRect()

        board_top = rect.bottom() - Board.BoardHeight * self.square_height()

        for i in range(Board.BoardHeight):
            for j in range(Board.board_width):
                shape = self.shape_at(j, Board.BoardHeight - i - 1)
                if shape != Tetrominoe.NoShape:
                    self.draw_square(
                        painter,
                        rect.left() + j * self.square_width(),
                        board_top + i * self.square_height(),
                        shape,
                    )

    def shape_at(self, x, y):
        return self.board[(y * Board.board_width) + x]

    def square_width(self):
        return self.contentsRect().width() // Board.board_width

    def square_height(self):
        return self.contentsRect().height() // Board.BoardHeight

    def draw_square(self, painter, x, y, shape):
        colors = [
            0x000000,
            0xCC6666,
            0x66CC66,
            0x6666CC,
            0xCCCC66,
            0xCC66CC,
            0x66CCCC,
            0xDAAA00,
        ]

        color = QColor(colors[shape])
        painter.fillRect(
            x + 1, y + 1, self.square_width() - 2, self.square_height() - 2, color
        )

        painter.setPen(color.lighter())
        painter.drawLine(x, y + self.square_height() - 1, x, y)
        painter.drawLine(x, y, x + self.square_width() - 1, y)

        painter.setPen(color.darker())
        painter.drawLine(
            x + 1,
            y + self.square_height() - 1,
            x + self.square_width() - 1,
            y + self.square_height() - 1,
        )
        painter.drawLine(
            x + self.square_width() - 1,
            y + self.square_height() - 1,
            x + self.square_width() - 1,
            y + 1,
        )


class Tetrominoe(object):
    """
    Enumeration for the different Tetrominoe shapes.
    """

    NoShape = 0
    ZShape = 1
    SShape = 2
    LineShape = 3
    TShape = 4
    SquareShape = 5
    LShape = 6
    MirroredLShape = 7


class Shape(object):
    """
    Representation of a Tetris piece with various shapes.
    """

    coordsTable = (
        ((0, 0), (0, 0), (0, 0), (0, 0)),
        ((0, -1), (0, 0), (-1, 0), (-1, 1)),
        ((0, -1), (0, 0), (1, 0), (1, 1)),
        ((0, -1), (0, 0), (0, 1), (0, 2)),
        ((-1, 0), (0, 0), (1, 0), (0, 1)),
        ((0, 0), (1, 0), (0, 1), (1, 1)),
        ((-1, -1), (0, -1), (0, 0), (0, 1)),
        ((1, -1), (0, -1), (0, 0), (0, 1)),
    )

    def __init__(self):
        """
        Initialize the shape with no specific shape.
        """
        self.coords = [[0, 0] for _ in range(4)]
        self.piece_shape = Tetrominoe.NoShape

        self.set_shape(Tetrominoe.NoShape)
        super().__init__()

    def shape(self):
        """
        Return the current shape.
        """
        return self.piece_shape

    def set_shape(self, shape):
        """
        Set the shape to the specified type.
        """
        table = Shape.coordsTable[shape]

        for i in range(4):
            for j in range(2):
                self.coords[i][j] = table[i][j]

        self.piece_shape = shape

    def set_random_shape(self):
        """
        Set the shape to a random type.
        """
        self.set_shape(random.randint(1, 7))

    def x(self, index):
        """
        Get the x-coordinate of the specified index.
        """
        return self.coords[index][0]

    def y(self, index):
        """
        Get the y-coordinate of the specified index.
        """
        return self.coords[index][1]

    def set_x(self, index, x):
        """
        Set the x-coordinate of the specified index.
        """
        self.coords[index][0] = x

    def set_y(self, index, y):
        """
        Set the y-coordinate of the specified index.
        """
        self.coords[index][1] = y

    def min_x(self):
        """
        Get the minimum x-coordinate of the shape.
        """
        m = self.coords[0][0]
        for i in range(4):
            m = min(m, self.coords[i][0])
        return m

    def max_x(self):
        """
        Get the maximum x-coordinate of the shape.
        """
        m = self.coords[0][0]
        for i in range(4):
            m = max(m, self.coords[i][0])
        return m

    def min_y(self):
        """
        Get the minimum y-coordinate of the shape.
        """
        m = self.coords[0][1]
        for i in range(4):
            m = min(m, self.coords[i][1])
        return m

    def max_y(self):
        """
        Get the maximum y-coordinate of the shape.
        """
        m = self.coords[0][1]
        for i in range(4):
            m = max(m, self.coords[i][1])
        return m

    def rotate_left(self):
        """
        Rotate the shape to the left.
        """
        if self.piece_shape == Tetrominoe.SquareShape:
            return self

        result = Shape()
        result.piece_shape = self.piece_shape

        for i in range(4):
            result.set_x(i, self.y(i))
            result.set_y(i, -self.x(i))

        return result

    def rotate_right(self):
        """
        Rotate the shape to the right.
        """
        if self.piece_shape == Tetrominoe.SquareShape:
            return self

        result = Shape()
        result.piece_shape = self.piece_shape

        for i in range(4):
            result.set_x(i, -self.y(i))
            result.set_y(i, self.x(i))

        return result


if __name__ == "__main__":
    app = QApplication(sys.argv)
    tetris = Tetris()
    sys.exit(app.exec())
