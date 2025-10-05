from flask import Flask, request, send_file, jsonify, render_template_string
import asyncio
import dns.asyncresolver
import dns.exception
from urllib.parse import urlparse
import threading
import time
import json
import os
from pathlib import Path
from datetime import datetime

app = Flask(__name__)

# GitHub Pages IPs
GITHUB_IPS = {
    "185.199.108.153", "185.199.109.153", "185.199.110.153", "185.199.111.153",
}

# Netlify common IPs
NETLIFY_IPS = {"75.2.60.5", "99.83.190.102"}
NETLIFY_CNAME_KEYWORDS = ["netlify.app", "netlify.com"]

# Jobs storage (memory তে রাখবে, production এ database ব্যবহার করবেন)
jobs = {}

def extract_domain(line: str) -> str:
    line = line.strip()
    if not line:
        return None
    if line.startswith("[") and line.endswith("]"):
        return line[1:-1]
    if not line.startswith("http://") and not line.startswith("https://"):
        line = "http://" + line
    try:
        return urlparse(line).hostname or None
    except ValueError:
        return None

async def check_dns(domain: str, resolver, timeout: float):
    is_github = False
    is_netlify = False
    try:
        answers_a = await resolver.resolve(domain, "A", lifetime=timeout)
        ips = [r.to_text() for r in answers_a]
        if any(ip in GITHUB_IPS for ip in ips):
            is_github = True
        elif any(ip in NETLIFY_IPS for ip in ips):
            is_netlify = True
    except dns.exception.DNSException:
        pass

    try:
        answers_cname = await resolver.resolve(domain, "CNAME", lifetime=timeout)
        for r in answers_cname:
            cname = r.to_text().lower()
            if any(k in cname for k in NETLIFY_CNAME_KEYWORDS):
                is_netlify = True
                break
    except dns.exception.DNSException:
        pass

    return is_github, is_netlify

async def process_batch_async(domains, job_id):
    """Background এ batch processing"""
    resolver = dns.asyncresolver.Resolver()
    timeout = 5.0
    
    github_domains = []
    netlify_domains = []
    other_domains = []
    
    total = len(domains)
    
    for idx, line in enumerate(domains):
        domain = extract_domain(line)
        
        if not domain:
            other_domains.append(line.strip())
            jobs[job_id]['processed'] = idx + 1
            jobs[job_id]['progress'] = round((idx + 1) / total * 100, 2)
            continue
        
        try:
            is_github, is_netlify = await check_dns(domain, resolver, timeout)
            
            if is_github:
                github_domains.append(domain)
            elif is_netlify:
                netlify_domains.append(domain)
            else:
                other_domains.append(line.strip())
        except:
            other_domains.append(line.strip())
        
        # Update progress
        jobs[job_id]['processed'] = idx + 1
        jobs[job_id]['progress'] = round((idx + 1) / total * 100, 2)
        jobs[job_id]['github_count'] = len(github_domains)
        jobs[job_id]['netlify_count'] = len(netlify_domains)
        jobs[job_id]['others_count'] = len(other_domains)
        
        # Small delay to avoid rate limiting
        if (idx + 1) % 50 == 0:
            await asyncio.sleep(0.5)
    
    # Save results
    jobs[job_id]['results'] = {
        'github': github_domains,
        'netlify': netlify_domains,
        'others': other_domains
    }
    jobs[job_id]['status'] = 'completed'
    jobs[job_id]['completed_at'] = datetime.now().isoformat()

def run_async_processing(domains, job_id):
    """Threading wrapper for async processing"""
    asyncio.run(process_batch_async(domains, job_id))

@app.route('/')
def home():
    return render_template_string('''
    <!DOCTYPE html>
    <html>
    <head>
        <title>Cloud Domain Processor - Offline Support</title>
        <style>
            * { margin: 0; padding: 0; box-sizing: border-box; }
            body { font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background: #f0f2f5; }
            .container { max-width: 900px; margin: 40px auto; padding: 20px; }
            .header { background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; padding: 30px; border-radius: 10px; margin-bottom: 30px; }
            .card { background: white; padding: 30px; border-radius: 10px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); margin-bottom: 20px; }
            textarea { width: 100%; height: 200px; padding: 15px; border: 2px solid #e0e0e0; border-radius: 8px; font-family: monospace; font-size: 14px; }
            button { background: #667eea; color: white; padding: 12px 30px; border: none; border-radius: 8px; cursor: pointer; font-size: 16px; font-weight: 600; }
            button:hover { background: #5568d3; }
            .info { background: #e3f2fd; padding: 15px; border-radius: 8px; border-left: 4px solid #2196f3; margin-top: 20px; }
            .jobs-link { display: inline-block; margin-top: 15px; color: #667eea; text-decoration: none; font-weight: 600; }
            .jobs-link:hover { text-decoration: underline; }
            .feature { display: flex; align-items: center; margin: 10px 0; }
            .feature::before { content: "✓"; color: #4caf50; font-weight: bold; margin-right: 10px; font-size: 18px; }
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <h1>☁️ Cloud Domain Processor</h1>
                <p style="margin-top: 10px; opacity: 0.9;">Upload করুন → Device বন্ধ করুন → পরে এসে Result নিন</p>
            </div>
            
            <div class="card">
                <h2 style="margin-bottom: 20px;">📤 Upload Domains</h2>
                <form action="/upload" method="post" enctype="multipart/form-data">
                    <input type="file" name="file" accept=".txt" required style="margin-bottom: 20px; padding: 10px;">
                    <br>
                    <button type="submit">🚀 Start Processing (Background)</button>
                </form>
                
                <div class="info">
                    <strong>🎯 Features:</strong>
                    <div class="feature">File upload করুন (txt format)</div>
                    <div class="feature">Background এ processing হবে</div>
                    <div class="feature">Device offline করতে পারবেন</div>
                    <div class="feature">পরে এসে result download করবেন</div>
                </div>
                
                <a href="/jobs" class="jobs-link">📊 View All Jobs →</a>
            </div>
            
            <div class="card">
                <h2 style="margin-bottom: 15px;">📝 Or Paste Domains</h2>
                <form action="/process" method="post">
                    <textarea name="domains" placeholder="example.com&#10;github.io&#10;netlify.app&#10;..." required></textarea>
                    <br><br>
                    <button type="submit">⚡ Process Now (Quick)</button>
                </form>
            </div>
        </div>
    </body>
    </html>
    ''')

@app.route('/upload', methods=['POST'])
def upload_file():
    if 'file' not in request.files:
        return "No file uploaded", 400
    
    file = request.files['file']
    if file.filename == '':
        return "No file selected", 400
    
    # Read domains from file
    domains = []
    for line in file.read().decode('utf-8').splitlines():
        if line.strip():
            domains.append(line.strip())
    
    # Create job
    job_id = f"job_{int(time.time())}_{len(jobs)}"
    jobs[job_id] = {
        'id': job_id,
        'status': 'processing',
        'total': len(domains),
        'processed': 0,
        'progress': 0,
        'github_count': 0,
        'netlify_count': 0,
        'others_count': 0,
        'created_at': datetime.now().isoformat(),
        'results': None
    }
    
    # Start background processing
    thread = threading.Thread(target=run_async_processing, args=(domains, job_id))
    thread.daemon = True
    thread.start()
    
    return f'''
    <!DOCTYPE html>
    <html>
    <head>
        <meta http-equiv="refresh" content="2;url=/job/{job_id}">
        <style>
            body {{ font-family: Arial; text-align: center; padding: 50px; background: #f0f2f5; }}
            .success {{ background: white; padding: 40px; border-radius: 10px; max-width: 500px; margin: 0 auto; box-shadow: 0 2px 10px rgba(0,0,0,0.1); }}
            .spinner {{ border: 4px solid #f3f3f3; border-top: 4px solid #667eea; border-radius: 50%; width: 50px; height: 50px; animation: spin 1s linear infinite; margin: 20px auto; }}
            @keyframes spin {{ 0% {{ transform: rotate(0deg); }} 100% {{ transform: rotate(360deg); }} }}
        </style>
    </head>
    <body>
        <div class="success">
            <h2>✅ Job Created!</h2>
            <div class="spinner"></div>
            <p>Job ID: <strong>{job_id}</strong></p>
            <p>Total domains: <strong>{len(domains):,}</strong></p>
            <p style="margin-top: 20px; color: #666;">Redirecting to job status page...</p>
            <p style="margin-top: 10px;"><a href="/job/{job_id}">View Status Now →</a></p>
        </div>
    </body>
    </html>
    '''

@app.route('/job/<job_id>')
def job_status(job_id):
    if job_id not in jobs:
        return "Job not found", 404
    
    job = jobs[job_id]
    
    # Auto-refresh if still processing
    refresh = '<meta http-equiv="refresh" content="3">' if job['status'] == 'processing' else ''
    
    return f'''
    <!DOCTYPE html>
    <html>
    <head>
        <title>Job Status - {job_id}</title>
        {refresh}
        <style>
            body {{ font-family: Arial; background: #f0f2f5; padding: 20px; }}
            .container {{ max-width: 800px; margin: 0 auto; }}
            .card {{ background: white; padding: 30px; border-radius: 10px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); margin-bottom: 20px; }}
            .progress-bar {{ width: 100%; height: 30px; background: #e0e0e0; border-radius: 15px; overflow: hidden; }}
            .progress-fill {{ height: 100%; background: linear-gradient(90deg, #667eea, #764ba2); transition: width 0.3s; }}
            .stat {{ display: inline-block; margin: 10px 20px 10px 0; padding: 10px 20px; background: #f5f5f5; border-radius: 8px; }}
            .download-btn {{ display: inline-block; margin: 10px 10px 10px 0; padding: 12px 24px; background: #4caf50; color: white; text-decoration: none; border-radius: 8px; }}
            .download-btn:hover {{ background: #45a049; }}
            .status-processing {{ color: #ff9800; }}
            .status-completed {{ color: #4caf50; }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="card">
                <h2>📊 Job Status: <span class="status-{job['status']}">{job['status'].upper()}</span></h2>
                <p>Job ID: <code>{job_id}</code></p>
                <p>Created: {job['created_at']}</p>
                
                <h3 style="margin-top: 30px;">Progress</h3>
                <div class="progress-bar">
                    <div class="progress-fill" style="width: {job['progress']}%"></div>
                </div>
                <p style="margin-top: 10px;"><strong>{job['processed']:,}</strong> / <strong>{job['total']:,}</strong> domains ({job['progress']}%)</p>
                
                <h3 style="margin-top: 30px;">Results</h3>
                <div class="stat">🐙 GitHub: <strong>{job['github_count']}</strong></div>
                <div class="stat">🌐 Netlify: <strong>{job['netlify_count']}</strong></div>
                <div class="stat">📋 Others: <strong>{job['others_count']}</strong></div>
                
                {f'''
                <h3 style="margin-top: 30px;">Download Results</h3>
                <a href="/download/{job_id}/github" class="download-btn">📥 GitHub.txt</a>
                <a href="/download/{job_id}/netlify" class="download-btn">📥 Netlify.txt</a>
                <a href="/download/{job_id}/others" class="download-btn">📥 Others.txt</a>
                <p style="margin-top: 15px; color: #666;">✅ Processing completed at {job.get('completed_at', 'N/A')}</p>
                ''' if job['status'] == 'completed' else '<p style="color: #ff9800; margin-top: 20px;">⏳ Processing in background... Page will auto-refresh</p>'}
                
                <p style="margin-top: 30px;"><a href="/jobs">← View All Jobs</a> | <a href="/">← New Job</a></p>
            </div>
        </div>
    </body>
    </html>
    '''

@app.route('/jobs')
def all_jobs():
    job_list = sorted(jobs.values(), key=lambda x: x['created_at'], reverse=True)
    
    rows = ''.join([f'''
    <tr>
        <td><a href="/job/{job['id']}">{job['id']}</a></td>
        <td><span class="status-{job['status']}">{job['status'].upper()}</span></td>
        <td>{job['processed']:,} / {job['total']:,}</td>
        <td>{job['progress']}%</td>
        <td>{job['created_at'][:19]}</td>
    </tr>
    ''' for job in job_list])
    
    return f'''
    <!DOCTYPE html>
    <html>
    <head>
        <title>All Jobs</title>
        <meta http-equiv="refresh" content="5">
        <style>
            body {{ font-family: Arial; background: #f0f2f5; padding: 20px; }}
            .container {{ max-width: 1200px; margin: 0 auto; }}
            .card {{ background: white; padding: 30px; border-radius: 10px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); }}
            table {{ width: 100%; border-collapse: collapse; margin-top: 20px; }}
            th, td {{ padding: 12px; text-align: left; border-bottom: 1px solid #e0e0e0; }}
            th {{ background: #f5f5f5; font-weight: 600; }}
            .status-processing {{ color: #ff9800; }}
            .status-completed {{ color: #4caf50; }}
            a {{ color: #667eea; text-decoration: none; }}
            a:hover {{ text-decoration: underline; }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="card">
                <h1>📋 All Jobs</h1>
                <p style="color: #666;">Auto-refreshing every 5 seconds...</p>
                <table>
                    <thead>
                        <tr>
                            <th>Job ID</th>
                            <th>Status</th>
                            <th>Progress</th>
                            <th>%</th>
                            <th>Created</th>
                        </tr>
                    </thead>
                    <tbody>
                        {rows if rows else '<tr><td colspan="5" style="text-align: center; color: #999;">No jobs yet</td></tr>'}
                    </tbody>
                </table>
                <p style="margin-top: 30px;"><a href="/">← Create New Job</a></p>
            </div>
        </div>
    </body>
    </html>
    '''

@app.route('/download/<job_id>/<category>')
def download(job_id, category):
    if job_id not in jobs or jobs[job_id]['status'] != 'completed':
        return "Job not found or not completed", 404
    
    results = jobs[job_id]['results']
    domains = results.get(category, [])
    
    content = '\n'.join(domains)
    
    from io import BytesIO
    return send_file(
        BytesIO(content.encode()),
        mimetype='text/plain',
        as_attachment=True,
        download_name=f'{category}.txt'
    )

@app.route('/process', methods=['POST'])
def process():
    domains_text = request.form.get('domains', '')
    domains = [d.strip() for d in domains_text.split('\n') if d.strip()]
    
    if not domains:
        return "No domains provided", 400
    
    # Quick processing (not background)
    results = asyncio.run(process_batch_async_quick(domains))
    
    return f'''[Previous quick process HTML - same as before]'''

async def process_batch_async_quick(domains):
    resolver = dns.asyncresolver.Resolver()
    timeout = 5.0
    github_domains = []
    netlify_domains = []
    other_domains = []
    
    for line in domains:
        domain = extract_domain(line)
        if not domain:
            other_domains.append(line.strip())
            continue
        
        try:
            is_github, is_netlify = await check_dns(domain, resolver, timeout)
            if is_github:
                github_domains.append(domain)
            elif is_netlify:
                netlify_domains.append(domain)
            else:
                other_domains.append(line.strip())
        except:
            other_domains.append(line.strip())
    
    return {'github': github_domains, 'netlify': netlify_domains, 'others': other_domains}

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8000))
    app.run(host='0.0.0.0', port=port, debug=False)
