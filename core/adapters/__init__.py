def join(thread, ms=3000):
    """Doi QThread thoat toi `ms`; qua han thi GIU no song toi luc xong, khong tha.

    Tha mot QThread con chay la Qt abort CA TIEN TRINH ("QThread: Destroyed while
    thread is still running"): luc do chinh thread giu ref cuoi, run() tra ve la
    no tu huy ngay trong thread cua minh. Do that 15/09/2026: mo REPLAY mot .tlog
    168 MB mat 4,26 s rieng khau mo file, stop() doi 3 s roi bo -> exit 134.

    Lambda giu `thread` qua closure; `finished` goi no o main thread, deleteLater()
    cat ket noi -> lambda va thread cung duoc giai phong.
    """
    if thread.wait(ms):
        return True
    thread.finished.connect(lambda: thread.deleteLater())
    return False
