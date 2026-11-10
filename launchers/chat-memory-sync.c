/* Named launcher so macOS Login Items shows "chat-memory-sync"
   instead of the Python interpreter. Runs: python3.15 run.py */
#include <unistd.h>
#include <sys/wait.h>

int main(void) {
    pid_t pid = fork();
    if (pid == 0) {
        char *argv[] = {
            "chat-memory-sync",
            "/Users/aayushgautam/ws/chat-memory/.sync/run.py",
            (char *)0
        };
        execv("/opt/homebrew/opt/python@3.15/bin/python3.15", argv);
        _exit(127);
    }
    int status = 0;
    waitpid(pid, &status, 0);
    return WIFEXITED(status) ? WEXITSTATUS(status) : 1;
}
