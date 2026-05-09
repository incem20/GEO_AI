import os
from dotenv import load_dotenv
from src.agent import run_agent
from src.visualizer import render_map

load_dotenv()

def main():
    print("\n" + "="*40)
    print("🌍 AfetRota: GeoAI Tahliye Asistanı")
    print("="*40 + "\n")
    
    semt = input("📍 Şu an hangi semttesin? (Örn: Beşiktaş, Fatih): ").strip()
    if not semt:
        semt = "Beşiktaş"

    query = f"{semt} tarafında depreme yakalandım, güvenli bir toplanma alanına nasıl giderim?"
    print(f"\n⏳ {semt} bölgesi taranıyor, en güvenli rota hesaplanıyor...")
    
    try:
        sonuc = run_agent(query)
        print("\n✅ --- Ajanın Raporu ---")
        print(sonuc.narrative)
        
        dosya_adi = f"tahliye_rotasi.html"
        render_map(sonuc, dosya_adi)
        
        print("\n🗺️ Harita başarıyla oluşturuldu!")
        print(f"👉 Dosyayı tarayıcıda açıp inceleyebilirsin: {dosya_adi}\n")
    except Exception as e:
        print(f"❌ Bir hata oluştu: {e}")

if __name__ == "__main__":
    main()