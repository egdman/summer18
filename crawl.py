import sys
import os
import re
import shutil
import asyncio
import aiohttp
from time import clock
from itertools import chain
from urllib import request, parse
from html.parser import HTMLParser
from argparse import ArgumentParser
from asyncio import Queue


def canonize(url):
  return re.sub(r'/+$', '', url.strip()) + '/'

def defrag(url):
  return parse.urlunsplit(parse.urlsplit(url)[:3] + ('',''))

def makeFilename(url):
  url = canonize(url)[:-1]
  return re.sub(r'/', '..', re.sub(r'^(\w*?)://', '', url))


class MyHTMLParser(HTMLParser):
  def __init__(self):
    super(MyHTMLParser, self).__init__()
    self.foundLinks = []


  def handle_starttag(self, _, attrs):
    self.foundLinks.extend(
      (value.strip() for name, value in attrs if value and name in ("href", "src")))


def canDecode(data, enc):
  def _canDecode(chunk):
    try:
      chunk.decode(enc)
      return True
    except UnicodeDecodeError:
      return False

  sz = len(data)
  for chunkSz in range(sz, sz - 5, -1):
    if _canDecode(data[:chunkSz]): return True
  return False


def doDecode(data, enc):
  try:
    return data.decode(enc)
  except UnicodeDecodeError:
    return ""


async def downloadAsync(istream, filename):
  chunkSz = 1024

  firstChunk = await istream.content.read(chunkSz)
  if not canDecode(firstChunk, "utf-8"):
    return ""

  fullContent = bytes()
  with open(filename, 'wb') as ostream:
    ostream.write(firstChunk)
    fullContent += firstChunk
    while True:
      chunk = await istream.content.read(chunkSz)
      if not chunk:
        break
      ostream.write(chunk)
      fullContent += chunk

  return doDecode(fullContent, "utf-8")


async def download_noexcept(url, session, filename):
  try:
    page = await session.get(url)

    try:
      return await downloadAsync(page, filename)
    finally:
      page.close()

  except Exception as ex:
    print("while downloading this link: '{}',".format(url))
    print("this happened: {} : {}".format(type(ex), ex))

  return ""


async def fetchAsync(url, root, eventLoop, filename, tempFilename):
  # dl to temp file
  pageText = ""
  async with aiohttp.ClientSession(loop = eventLoop) as session:
    pageText = await download_noexcept(url, session, tempFilename)

  # parse text to find links
  parser = MyHTMLParser()
  parser.feed(pageText)
  absLinks = (defrag(parse.urljoin(url, link)) for link in parser.foundLinks)
  absLinks = set(link for link in absLinks if os.path.commonprefix((link, root)) == root)

  # write links to disk
  linkFilename = tempFilename + ".links"
  with open(linkFilename, "w") as stream:
    stream.write('\n'.join(absLinks))
  
  try:
    shutil.move(tempFilename, filename)
  except OSError:
    pass

  return url, absLinks


def filenames(inputPath):
  for _, _, filenames in os.walk(inputPath):
    for filename in filenames:
      yield filename


class Spider(object):
  def __init__(self, rootUrl, rootDir, tempDir):
    self.root = rootUrl
    self.rootDir = rootDir
    self.tempDir = tempDir

    self.queue = Queue()
    self.pending = set()
    self.down = set(filenames(self.rootDir))

    # read cached links
    uniqLinks = set([rootUrl])
    try:
      for linkFile in filenames(self.tempDir):
        if not linkFile.endswith(".links"):
          continue

        with open(os.path.join(self.tempDir, linkFile), 'r') as stream:
          for link in stream.read().strip().splitlines():
            uniqLinks.add(link)

    except OSError:
      pass

    for link in uniqLinks:
      if makeFilename(link) not in self.down:
        self.queue.put_nowait(link)



  async def cleanQueue(self):
    while True:
      await asyncio.sleep(2)
      uniqLinks = set()
      while not self.queue.empty():
        uniqLinks.add(self.queue.get_nowait())

      for link in uniqLinks:
        self.queue.put_nowait(link)


  async def monitor(self):
    while True:
      await asyncio.sleep(2)
      print("{} down, {} pending".format(len(self.down), len(self.pending)))
  

  async def run(self, eventLoop):
    monitorTask = asyncio.ensure_future(self.monitor())
    cleanTask = asyncio.ensure_future(self.cleanQueue())

    def whenDownloaded(task):
      thisLink, nextLinks = task.result()

      self.pending.remove(thisLink)
      self.down.add(makeFilename(thisLink))

      newLinks = (link for link in nextLinks if makeFilename(link) not in self.down)

      for link in newLinks:
        self.queue.put_nowait(link)

    while True:

      if len(self.pending) >= 100: # too many tasks
        await asyncio.sleep(.01)

      elif not self.queue.empty():
        link = defrag(await self.queue.get())

        if link not in self.pending:
          self.pending.add(link)
          filename = os.path.join(self.rootDir, makeFilename(link))
          tempFilename = os.path.join(self.tempDir, makeFilename(link))
          task = asyncio.ensure_future(fetchAsync(link, self.root, eventLoop, filename, tempFilename))
          task.add_done_callback(whenDownloaded)


      elif len(self.pending) == 0:
        break

      else:
        await asyncio.sleep(.01)

    monitorTask.cancel()
    cleanTask.cancel()
    print("{} down".format(len(self.down)))


def main():
  parser = ArgumentParser()
  parser.add_argument("url", type=str, help="URL to explore")

  args = parser.parse_args()
  rootUrl = canonize(args.url)  

  downloadTo = makeFilename(rootUrl)
  print("downloading to: " + downloadTo)
  if not os.path.exists(downloadTo):
      os.mkdir(downloadTo)

  tempDir = downloadTo + ".temp"
  if not os.path.exists(tempDir):
      os.makedirs(tempDir)

  def handler(loop, context):
    pass

  started = clock()
  spider = Spider(rootUrl, downloadTo, tempDir)
  loop = asyncio.get_event_loop()
  loop.set_exception_handler(handler)
  try:
    loop.run_until_complete(spider.run(loop))

    # cleanup temp directory
    try:
      shutil.rmtree(tempDir)
    except OSError as ex:
      print(ex)

    print("done")
  except KeyboardInterrupt as ex:
    loop.call_exception_handler({"exception": ex})
    print("interrupted")

  print("{:.1f} seconds".format(clock() - started))


if __name__ == '__main__': main()
