import os
import sys

# Ensure project root is on PATH
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from flask import Flask
from app.models import db, User, Configuration

def seed():
    # Setup a temp app context
    app = Flask(__name__)
    db_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'konn3ct.db')
    app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{db_path}'
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    
    db.init_app(app)
    
    with app.app_context():
        print("Recreating database tables...")
        db.drop_all()
        db.create_all()
        
        print("Seeding default users...")
        
        # Create Admin
        admin = User(username='admin', role='Admin', api_key='admin-api-key-9999')
        admin.set_password('adminpass')
        db.session.add(admin)
        
        # Create Operator
        operator = User(username='operator', role='Operator', api_key='operator-api-key-8888')
        operator.set_password('operatorpass')
        db.session.add(operator)
        
        # Create Viewer
        viewer = User(username='viewer', role='Viewer', api_key='viewer-api-key-7777')
        viewer.set_password('viewerpass')
        db.session.add(viewer)
        
        print("Seeding the 7 Preconfigured Test Profiles...")
        
        # 1. Sprint 1 Diagnostic Test
        cfg1 = Configuration(
            name="Sprint 1 Diagnostic Test",
            description="10-Bot diagnostic validation focusing on chat delivery, screen share capability, and full action lifecycle state confirmation.",
            room="strategy-meeting",
            bots=10,
            stagger=0.5,
            batch=2,
            concurrency=10,
            webrtc_enabled=True,
            media_quality="low",
            max_subscriptions=2,
            decode_downlink=False,
            test_scenarios="camera_toggle,mic_toggle,hand_raise,chat,screen_share",
            action_interval=15.0,
            chat_interval=25.0,
            confirm_timeout=5.0,
            max_retries=5,
            frontend="https://edge.konn3ct.net",
            signal="konn3ctedge.konn3ct.net",
            jwt_secret="fallback-secret-key",
            browser_distribution="chrome:30,safari:20,firefox:15,edge:10,brave:5,chrome_mobile:10,safari_mobile:5,opera:3,samsung:2",
            device_distribution="desktop:70,mobile:20,tablet:10",
            os_distribution="windows:40,macos:30,linux:10,ios:12,android:8"
        )
        db.session.add(cfg1)
        
        # 2. 50-Bot Regression Test
        cfg2 = Configuration(
            name="50-Bot Regression Test",
            description="Simulates 50 bots + 1 host with a full mix of browsers, devices, and network profiles to compare against performance baselines.",
            room="testinggg",
            bots=50,
            stagger=1.0,
            batch=5,
            concurrency=50,
            webrtc_enabled=True,
            media_quality="medium",
            max_subscriptions=2,
            decode_downlink=False,
            test_scenarios="camera_toggle,mic_toggle,hand_raise,chat",
            action_interval=25.0,
            chat_interval=40.0,
            confirm_timeout=5.0,
            max_retries=5,
            frontend="https://edge.konn3ct.net",
            signal="konn3ctedge.konn3ct.net",
            jwt_secret="fallback-secret-key",
            browser_distribution="chrome:40,safari:20,firefox:20,edge:10,brave:10",
            device_distribution="desktop:80,mobile:15,tablet:5",
            os_distribution="windows:50,macos:30,linux:20"
        )
        db.session.add(cfg2)
        
        # 3. 100-Bot Load Test
        cfg3 = Configuration(
            name="100-Bot Load Test",
            description="Simulates 100 bots + 1 host. Focuses on testing WebSocket fan-out and UI rendering latency under scale.",
            room="highload",
            bots=100,
            stagger=1.0,
            batch=10,
            concurrency=100,
            webrtc_enabled=True,
            media_quality="medium",
            max_subscriptions=2,
            decode_downlink=False,
            test_scenarios="camera_toggle,mic_toggle,hand_raise,chat",
            action_interval=30.0,
            chat_interval=60.0,
            confirm_timeout=5.0,
            max_retries=5,
            frontend="https://edge.konn3ct.net",
            signal="konn3ctedge.konn3ct.net",
            jwt_secret="fallback-secret-key",
            browser_distribution="chrome:50,firefox:30,edge:20",
            device_distribution="desktop:100,mobile:0,tablet:0",
            os_distribution="windows:60,linux:40"
        )
        db.session.add(cfg3)
        
        # 4. 250-Bot Load Test
        cfg4 = Configuration(
            name="250-Bot Load Test",
            description="Simulates 250 bots focusing on backend broadcast stability and SFU WebRTC subscription limits.",
            room="broadcasting",
            bots=250,
            stagger=1.5,
            batch=15,
            concurrency=150,
            webrtc_enabled=True,
            media_quality="low",
            max_subscriptions=1,
            decode_downlink=False,
            test_scenarios="camera_toggle,mic_toggle,chat",
            action_interval=35.0,
            chat_interval=60.0,
            confirm_timeout=10.0,
            max_retries=5,
            frontend="https://edge.konn3ct.net",
            signal="konn3ctedge.konn3ct.net",
            jwt_secret="fallback-secret-key",
            browser_distribution="chrome:40,safari:20,firefox:20,edge:10,brave:10",
            device_distribution="desktop:80,mobile:15,tablet:5",
            os_distribution="windows:50,macos:30,linux:20"
        )
        db.session.add(cfg4)
        
        # 5. 500-Bot Stress Test
        cfg5 = Configuration(
            name="500-Bot Stress Test",
            description="Simulates 500 bots. Focuses on server CPU/RAM usage thresholds, concurrent sockets handling, and maximum bandwidth stress.",
            room="stresstest",
            bots=500,
            stagger=2.0,
            batch=20,
            concurrency=250,
            webrtc_enabled=False,
            media_quality="low",
            max_subscriptions=0,
            decode_downlink=False,
            test_scenarios="chat,hand_raise",
            action_interval=30.0,
            chat_interval=50.0,
            confirm_timeout=10.0,
            max_retries=5,
            frontend="https://edge.konn3ct.net",
            signal="konn3ctedge.konn3ct.net",
            jwt_secret="fallback-secret-key",
            browser_distribution="chrome:50,firefox:30,edge:20",
            device_distribution="desktop:100,mobile:0,tablet:0",
            os_distribution="windows:60,linux:40"
        )
        db.session.add(cfg5)
        
        # 6. Soak Test
        cfg6 = Configuration(
            name="Soak Test",
            description="50-100 bots running for 30-60 minutes to uncover memory leaks, network degradation patterns, and connection dropouts.",
            room="soaktest",
            bots=60,
            stagger=1.0,
            batch=5,
            concurrency=60,
            webrtc_enabled=True,
            media_quality="low",
            max_subscriptions=2,
            decode_downlink=False,
            leave=45, # 45 minutes duration
            network_degradation=True,
            degradation_interval=180,
            test_scenarios="camera_toggle,mic_toggle,chat",
            action_interval=40.0,
            chat_interval=60.0,
            confirm_timeout=5.0,
            max_retries=5,
            frontend="https://edge.konn3ct.net",
            signal="konn3ctedge.konn3ct.net",
            jwt_secret="fallback-secret-key",
            browser_distribution="chrome_mobile:40,safari_mobile:30,samsung:20,firefox_mobile:10",
            device_distribution="desktop:0,mobile:70,tablet:30",
            os_distribution="ios:40,android:60"
        )
        db.session.add(cfg6)
        
        # 7. Browser Compatibility Test
        cfg7 = Configuration(
            name="Browser Compatibility Test",
            description="20 bots with a fixed distribution representing every browser client type and OS platform supported by the fingerprint engine.",
            room="compatibility",
            bots=20,
            stagger=1.0,
            batch=2,
            concurrency=20,
            webrtc_enabled=True,
            media_quality="low",
            max_subscriptions=2,
            decode_downlink=False,
            test_scenarios="camera_toggle,mic_toggle,hand_raise,chat,screen_share",
            action_interval=20.0,
            chat_interval=30.0,
            confirm_timeout=5.0,
            max_retries=5,
            frontend="https://edge.konn3ct.net",
            signal="konn3ctedge.konn3ct.net",
            jwt_secret="fallback-secret-key",
            browser_distribution="chrome:2,safari:2,firefox:2,edge:2,brave:2,opera:2,chrome_mobile:2,safari_mobile:2,samsung:2,firefox_mobile:1,opera_mobile:1",
            device_distribution="desktop:12,mobile:6,tablet:2",
            os_distribution="windows:6,macos:4,linux:2,ios:4,android:4"
        )
        db.session.add(cfg7)
        
        db.session.commit()
        print("Database seeded successfully with all 7 profiles!")

if __name__ == '__main__':
    seed()
