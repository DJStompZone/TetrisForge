```
QObject::setParent: Cannot set parent, new parent is in a different thread
QLayout: Cannot add parent widget Board/ to its child layout QHBoxLayout/
Network loop error: 'utf-8' codec can't decode bytes in position 4-5: unexpected end of data
Traceback (most recent call last):
  File "C:\Users\Admin\tetris.py", line 332, in network_loop
    self.game.start_game_from_network(True, False)
  File "C:\Users\Admin\tetris.py", line 94, in start_game_from_network
    self.start_game(
  File "C:\Users\Admin\tetris.py", line 105, in start_game
    self.tboard = Board(
                  ^^^^^^
  File "C:\Users\Admin\tetris.py", line 375, in __init__
    self.init_board()
  File "C:\Users\Admin\tetris.py", line 493, in init_board
    decoded = base64.b64decode(self.join_code.encode()).decode()
              ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
UnicodeDecodeError: 'utf-8' codec can't decode bytes in position 4-5: unexpected end of data
```

