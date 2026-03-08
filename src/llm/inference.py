import atexit
import logging
import os
import random
import signal
import subprocess
import time
from pathlib import Path

import requests

from utils.app_logger import AppLogger
from utils.folders import Folders


LLAMACPP_SERVER_PATH = Path(".inference/llama.cpp/bin")
LLAMACPP_SRV_EXECUTABLE = Path("llama-server.exe")
SERVER_BIN = str(Folders.root / LLAMACPP_SERVER_PATH / LLAMACPP_SRV_EXECUTABLE)

AVAILABLE_MODELS = {
    "Qwen3-0.6B-abliterated-Q4_K_S": {
        "type": "general",
        "speed": 210,
        "default_args": True,
        "args": {
            "model": "C:/llama_cpp_models/ABL/Qwen3-0.6B-abliterated-Q4_K_S.gguf",
            "n-gpu-layers": "999",
            "ctx-size": "2048",
            "n-predict": "1024",
            "flash-attn": True,
            "batch-size": "16",
            "ubatch-size": "8",
            "temp": "0.6",
            "top-p": "0.95",
            "top-k": "20",
        },
    },
    "Qwen3-0.6B-Q4_K_S": {
        "type": "general",
        "speed": 200,
        "default_args": True,
        "args": {
            "model": "C:/llama_cpp_models/Qwen/Qwen3-0.6B-Q4_K_S.gguf",
            "n-gpu-layers": "999",
            "ctx-size": "2048",
            "n-predict": "1024",
            "flash-attn": True,
            "batch-size": "16",
            "ubatch-size": "8",
            "temp": "0.6",
            "top-p": "0.95",
            "top-k": "20",
        },
    },
    "Qwen3-1.7B-abliterated-Q4_K_S": {
        "type": "general",
        "speed": 120,
        "default_args": True,
        "args": {
            "model": "C:/llama_cpp_models/ABL/Qwen3-1.7B-abliterated-Q4_K_S.gguf",
        },
    },
    "Qwen3-4B-abliterated-Q4_K_S": {
        "type": "general",
        "speed": 60,
        "default_args": True,
        "args": {
            "model": "C:/llama_cpp_models/Qwen/Qwen3-4B-abliterated-Q4_K_S.gguf",
        },
    },
    "Qwen3-8B-abliterated-Q4_K_S": {
        "type": "general",
        "speed": "normal",
        "default_args": True,
        "args": {
            "model": "C:/llama_cpp_models/Qwen/Qwen3-8B-abliterated-Q4_K_S.gguf",
        },
    },
    "DeepSeek-R1-0528-Qwen3-8B-abliterated.Q4_K_S": {
        "type": "general",
        "speed": 30,
        "default_args": True,
        "args": {
            "model": "C:/llama_cpp_models/Qwen/DeepSeek-R1-0528-Qwen3-8B-abliterated.Q4_K_S.gguf",
        },
    },
    "InternVL3-1B-Q4_K_S": {
        # TODO: images resize to 448px see: https://huggingface.co/OpenGVLab/InternVL3-1B-Instruct
        "type": "multimodal",
        "speed": 120,
        "default_args": False,
        "args": {
            "host": "127.0.0.1",
            "port": 8080,
            "model": "C:/llama_cpp_models/InternVL3-Instruct/InternVL3-1B-Instruct.Q4_K_S.gguf",
            "mmproj": "C:/llama_cpp_models/InternVL3-Instruct/InternVL3-1B-Instruct.mmproj-Q8_0.gguf",
            "n-gpu-layers": "999",
            "ctx-size": "32768",
            "n-predict": "2048",
            "flash-attn": True,
            "batch-size": "64",
            "ubatch-size": "32",
            "temp": "0.6",
            "top-p": "0.95",
            "top-k": "20",
            "threads": 3,
            "swa-full": True,
        },
    },
    "Nanonets-OCR-s-Q4_K_S": {
        "type": "multimodal.ocr",
        "speed": 150,
        "default_args": True,
        "args": {
            "model": "C:/llama_cpp_models/Nanonets/Nanonets-OCR-s-Q4_K_S.gguf",
            "mmproj": "C:/llama_cpp_models/Nanonets/mmproj-BF16.gguf",
        },
    },
    "Orsta-7B.Q3_K_S": {
        "type": "multimodal.ocr",
        "speed": 20,
        "default_args": True,
        "args": {
            "model": "C:/llama_cpp_models/Ostra/Orsta-7B.Q3_K_S.gguf",
            "mmproj": "C:/llama_cpp_models/Ostra/Orsta-7B.mmproj-Q8_0.gguf",
        },
    },
    "SmolLM3-3B-Q4_K_S": {
        "type": "multimodal",
        "speed": 70,
        "default_args": True,
        "args": {
            "model": "C:/llama_cpp_models/SmolVLM/SmolLM3-3B-Q4_K_S.gguf",
        },
    },
    "Gemma-3-4b-it-q4_0": {
        "type": "multimodal",
        "speed": 40,
        "default_args": False,
        "args": {
            "host": "127.0.0.1",
            "port": 8080,
            "n-gpu-layers": "999",
            "ctx-size": "32768",
            "n-predict": "2048",
            "model": "C:/llama_cpp_models/Gemma/gemma-3-4b-it-q4_0.gguf",
            "mmproj": "C:/llama_cpp_models/Gemma/gemma-3-4b-it-q4_0.mmproj-f16-4B.gguf",
        },
    },
    "Gemma-3n-E4B-it-Q4_K_S": {
        "type": "general",
        "speed": 50,
        "default_args": True,
        "args": {
            "model": "C:/llama_cpp_models/Gemma/google_gemma-3n-E4B-it-Q4_K_S.gguf",
        },
    },
}

class LlamaCppServer:

    DEFAULT_ARGS = {
        "host": "127.0.0.1",
        "port": 8080,
        "seed": round(random.uniform(0, 1000000)),
        "n_gpu_layers": 999,
        "ctx_size": 2048,
        "n_predict": 1024,
        "flash_attn": True,
        "batch_size": 32,
        "ubatch_size": 16,
        "temp": 0.6,
        "top_p": 0.95,
        "top_k": 20,
        "min_p": 0.01,
        "presence_penalty": 0,
        "no_context_shift": True,
        "threads": 1,
        "swa_full": True,
    }

    def __init__(
        self,
        model: dict,
    ):
        self.logger = AppLogger(name=self.__class__.__name__, log_level=logging.DEBUG)
        self.model = model
        self.process = None
        self.host = None
        self.port = None
        self.model_name = None
        self.guard_for_termination()
        self.initialize_args()

    def guard_for_termination(self):
        """Guard against server not stopping properly and clears the memory in such cases"""
        atexit.register(self.stop)
        # Signal handlers can only be registered from the main thread
        import threading
        if threading.current_thread() is not threading.main_thread():
            return
        for sig in [signal.SIGINT, signal.SIGTERM]:
            prev_handler = signal.getsignal(sig)

            def handler(signum, frame):
                self.stop()
                if prev_handler and callable(prev_handler):
                    prev_handler(signum, frame)

            signal.signal(sig, handler)

    def initialize_args(self):
        args = self.model.get("args", {})
        if not args:
            raise ValueError("Model args are required")

        if not os.path.exists(SERVER_BIN):
            raise FileNotFoundError(f"Server executable not found: {SERVER_BIN}")

        model_path = args.get("model")
        if not os.path.exists(model_path):
            raise FileNotFoundError(f"Model not found: {model_path}")

        mmproj_path = args.get("mmproj_path")
        if mmproj_path and not os.path.exists(mmproj_path):
            raise FileNotFoundError(f"MMProj not found: {mmproj_path}")

        model_args = self.model.get("args", {})
        use_default_args = self.model.get("default_args", False)

        if use_default_args:
            args = self.DEFAULT_ARGS.copy()
        else:
            args = {}

        if model_args:
            args.update(model_args)

        self.model["args"] = args
        self.model_name = Path(args.get("model")).stem

    def start(self, silent=False, stdout=None):
        if self.process:
            self.logger.debug("Server is already running.")
            return

        arg_list = []
        args = self.model.get("args", {})
        for arg_k, arg_v in args.items():
            if arg_v is True:
                arg_list.append(f"--{arg_k}")
            else:
                arg_list.append(f"--{arg_k}")
                arg_list.append(str(arg_v))

        cmd = [SERVER_BIN, *arg_list]
        self.logger.debug(f"Starting server with command: {' '.join(cmd)}")

        stderr = subprocess.STDOUT
        if silent:
            stdout = subprocess.DEVNULL
            stderr = subprocess.DEVNULL

        self.host = args.get("host", "127.0.0.1")
        self.port = args.get("port", 8080)

        start_message = f"Server at http://{self.host}:{self.port}"
        self.process = subprocess.Popen(cmd, stdout=stdout, stderr=stderr)

        for _ in range(60):
            # Connect to the server to check availability with retry for max 60 sec
            try:
                response = requests.get(f"http://{self.host}:{self.port}/v1/models", timeout=2)
                if response.status_code == 200:
                    resp_j = response.json()["models"][0]["name"].split("/")[-1]
                    self.logger.info(f"{start_message} :: LLM Model: {resp_j} :: Status: Ready, up and running!")
                    return
            except:
                pass
            time.sleep(1)
        self.logger.error(f"{start_message} :: Status: Error, server failed to start!")
        raise RuntimeError(f"Server at http://{self.host}:{self.port} failed to start")

    def is_running(self):
        return self.process and self.process.poll() is None

    def is_up_and_running(self):
        response = requests.get(f"http://{self.host}:{self.port}/v1/models", timeout=2)
        if response.status_code == 200:
            return True
        return False

    def stop(self):
        if self.process:
            self.logger.debug(f"Stopping server ({Path(self.model.get("path","")).stem}) http://{self.host}:{self.port}")
            self.process.terminate()
            self.process.wait()
            self.process = None
            self.logger.debug(f"Server http://{self.host}:{self.port} has gracefully stopped.")

    def generate(self, prompt: str, max_tokens: int = 10240) -> str:
        response = requests.post(
            f"http://{self.host}:{self.port}/completion", json={"prompt": prompt, "max_tokens": max_tokens}, timeout=30
        )
        response.raise_for_status()
        return response.json().get("content", "").strip()

    def chat(self, messages: list, max_tokens: int = 10240) -> str:
        response = requests.post(
            f"http://{self.host}:{self.port}/v1/chat/completions",
            json={"messages": messages, "max_tokens": max_tokens, "stream": False},
            timeout=30,
        )
        response.raise_for_status()
        return response.json()["choices"][0]["message"]["content"].strip()


OPTI_DEFAULT_MODEL_NAMES = [
    "Qwen3-0.6B-abliterated-Q4_K_S",
    "Qwen3-1.7B-abliterated-Q4_K_S",
    "InternVL3-1B-Q4_K_S",
]


def get_default_config():
    """Build default config lazily — only instantiates servers for models that exist on disk."""
    servers = []
    for name in OPTI_DEFAULT_MODEL_NAMES:
        try:
            servers.append(LlamaCppServer(AVAILABLE_MODELS[name]))
        except (FileNotFoundError, KeyError) as e:
            import logging
            logging.warning(f"Skipping model {name}: {e}")
    return servers


class Inference:
    """Service for handling LLM inference"""

    def __init__(
        self,
        event_bus=None,
        models=None,
    ):
        self.name = self.__class__.__name__
        self.logger = AppLogger(name=self.name, log_level=logging.DEBUG)
        self.event_bus = event_bus
        if models:
            self.models = models
        else:
            self.models = get_default_config()
        self.started = []
        # Shorthands for basic types of models used for various tasks
        self.fast = None
        self.text = None
        self.multimodal = None
        # TODO: Add more shorthands for different types of models e.g. TTS, STT, etc. when or if will be available
        #       self.ocr = None
        #       self.navigator = None

    def get_good_port(self, m, surl, host, port):
        """Get a good port to use for the server"""
        while surl in self.started or port > 65535:
            self.logger.debug(f"Port {host}:{port} already in use, trying {port + 1}")
            port += 1
            m.model["args"]["port"] = port
            m.port = port
            surl = f"{host}:{port}"
        return surl

    def set_shorthands(self, m):
        """Set shorthands for basic types of models used for various tasks,
        will set the fastest model as the fast one and the text model as the most knowledgeable one"""
        # Set the text model if not set yet
        if not self.text:
            self.text = m
        # Set the fast model if not set yet
        if not self.fast:
            self.fast = m
        # Set the fast model to the fastest one
        if m.model["speed"] > self.fast.model["speed"]:
            self.fast = m
        # Set the text model to the most knowledgeable one
        if m.model["speed"] < self.text.model["speed"]:
            self.text = m
        # Set the multimodal model if not set yet
        if m.model["type"] == "multimodal" and not self.multimodal:
            self.multimodal = m
        # Set the multimodal model to the fastest one
        if m.model["type"] == "multimodal":
            if m.model["speed"] > self.multimodal.model["speed"]:
                self.multimodal = m

    def initialize(self, silent=True):
        self.logger.info("Initializing Inference ...")
        try:
            for m in self.models:
                args = m.model.get("args", {})
                self.logger.debug(f"Starting server with args: {args}")
                host = args.get("host")
                port = int(args.get("port"))
                surl = f"{host}:{port}"
                surl = self.get_good_port(m, surl, host, port)
                self.started.append(surl)
                m.start(silent=silent)
                self.set_shorthands(m)

            self.logger.info(f"Fast model: {self.fast.model_name if self.fast else 'Not available'}")
            self.logger.info(f"Text model: {self.text.model_name if self.text else 'Not available'}")
            self.logger.info(f"Multimodal model: {self.multimodal.model_name if self.multimodal else 'Not available'}")

        except Exception as e:
            self.logger.error("Error Starting API servers", e)

    def cleanup(self):
        self.logger.info("Cleaning up ...")
        try:
            for model in self.models:
                model.stop()
        except Exception as e:
            self.logger.error("Error Stoping API servers", e)


def main():
    inf = Inference()
    try:
        inf.initialize()
        # Keep running until Ctrl+C
        while True or KeyboardInterrupt:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nShutting down...")
    finally:
        inf.cleanup()


if __name__ == "__main__":
    main()
