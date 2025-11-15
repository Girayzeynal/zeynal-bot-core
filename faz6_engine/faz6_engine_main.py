from .faz6_test import run_faz6_test

def run_faz6_engine():
    try:
        return run_faz6_test()
    except Exception as e:
        return f"FAZ-6 TEST MODÜL HATASI: {str(e)}" 
